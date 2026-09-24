"""Job execution.

``LocalProcessRunner`` runs jobs on a thread pool; every CAD job (geometry analysis, drawing
generation) runs in its own subprocess with a timeout and an address-space limit, so a
malformed file cannot crash or exhaust the API process. Subprocesses speak a JSON-lines
protocol on stdout (``progress`` / ``result`` / ``error``). A Redis/RQ runner with the same
``submit`` interface is planned for multi-host deployment.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from cad_api.config import Settings
from cad_api.db import CadModel, Database, Job, JobKind, JobState, ModelStatus
from cad_api.services.storage import Storage

log = logging.getLogger(__name__)


class JobRunner(Protocol):
    def submit(self, job_id: str) -> None: ...
    def shutdown(self) -> None: ...


def _limit_resources(memory_bytes: int):  # pragma: no cover - runs in the child
    def apply() -> None:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return apply


@dataclass
class ProcessOutcome:
    rc: int
    result: dict | None
    error: dict | None
    killed: bool
    stderr_tail: str


class LocalProcessRunner:
    def __init__(self, settings: Settings, db: Database, storage: Storage) -> None:
        self.settings, self.db, self.storage = settings, db, storage
        self.pool = ThreadPoolExecutor(max_workers=settings.job_workers, thread_name_prefix="job")

    def submit(self, job_id: str) -> None:
        self.pool.submit(self._run_safely, job_id)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=False)

    # ------------------------------------------------------------------ bookkeeping

    def _update(self, job_id: str, **fields) -> None:
        with self.db.sessions() as s:
            job = s.get(Job, job_id)
            for k, v in fields.items():
                setattr(job, k, v)
            s.commit()

    def _run_safely(self, job_id: str) -> None:
        try:
            with self.db.sessions() as s:
                kind = s.get(Job, job_id).kind
            if kind == JobKind.DRAWING:
                self._run_drawing(job_id)
            else:
                self._run_analysis(job_id)
        except Exception as exc:  # noqa: BLE001 - never lose a job silently
            log.exception("job crashed", extra={"job_id": job_id})
            self._fail(job_id, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")

    def _fail(self, job_id: str, code: str, message: str, *, model_failed: bool = False) -> None:
        with self.db.sessions() as s:
            job = s.get(Job, job_id)
            job.state, job.error_code, job.error_message = JobState.FAILED, code, message[:2000]
            job.finished_at = datetime.now(UTC)
            if model_failed:
                s.get(CadModel, job.model_id).status = ModelStatus.FAILED
            s.commit()

    def _fail_from(self, job_id: str, out: ProcessOutcome, *, model_failed: bool) -> None:
        if out.error:
            self._fail(job_id, out.error.get("code", "JOB_FAILED"), out.error.get("message", "job failed"),
                       model_failed=model_failed)
        elif out.killed:
            self._fail(job_id, "JOB_TIMEOUT", f"job exceeded {self.settings.analysis_timeout_s}s",
                       model_failed=model_failed)
        elif out.rc < 0:
            self._fail(job_id, "JOB_KILLED", f"process terminated by signal {-out.rc} (e.g. memory limit)",
                       model_failed=model_failed)
        else:
            # surface the last line of the child's stderr (e.g. "ModuleNotFoundError: ...") - never file contents
            last = next((ln.strip() for ln in reversed(out.stderr_tail.splitlines()) if ln.strip()), "")
            detail = f": {last[:300]}" if last else ""
            self._fail(job_id, "JOB_CRASHED", f"process exited with code {out.rc}{detail}", model_failed=model_failed)
        log.warning("job failed rc=%s stderr_tail=%s", out.rc, out.stderr_tail[-2000:], extra={"job_id": job_id})

    # ------------------------------------------------------------------ subprocess

    def _run_process(self, job_id: str, argv: list[str], cwd: Path,
                     on_progress: Callable[[dict], None]) -> ProcessOutcome:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "HOME": str(cwd),
               "OMP_NUM_THREADS": "1", "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(cwd / ".mpl")}
        preexec = (_limit_resources(self.settings.analysis_memory_mb * 1024 * 1024)
                   if sys.platform.startswith("linux") else None)
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [self.settings.analysis_python, *argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=cwd, env=env, text=True, preexec_fn=preexec,  # noqa: PLW1509
        )
        killed = threading.Event()

        def kill() -> None:
            killed.set()
            proc.kill()

        timer = threading.Timer(self.settings.analysis_timeout_s, kill)
        timer.start()
        result = error = None
        tail: list[str] = []

        def drain() -> None:
            for line in proc.stderr:  # bounded tail for diagnostics
                tail.append(line)
                del tail[:-40]

        t_err = threading.Thread(target=drain, daemon=True)
        t_err.start()
        try:
            for line in proc.stdout:
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if evt.get("event") == "progress":
                    on_progress(evt)
                elif evt.get("event") == "result":
                    result = evt
                elif evt.get("event") == "error":
                    error = evt
            rc = proc.wait()
        finally:
            timer.cancel()
            t_err.join(timeout=5)
        return ProcessOutcome(rc=rc, result=result, error=error, killed=killed.is_set(), stderr_tail="".join(tail))

    # ------------------------------------------------------------------ analysis

    def _run_analysis(self, job_id: str) -> None:
        with self.db.sessions() as s:
            job = s.get(Job, job_id)
            model = s.get(CadModel, job.model_id)
            model_id, fmt, filename = model.id, model.format, model.original_filename
            job.state, job.started_at, job.message = JobState.ANALYZING, datetime.now(UTC), "Starting analysis"
            model.status = ModelStatus.ANALYZING
            s.commit()
        work = self.storage.job_dir(job_id)
        argv = ["-m", "geometry_service", "analyze", "--input", str(self.storage.model_source(model_id, fmt)),
                "--format", fmt, "--output-dir", str(work), "--filename", filename]
        log.info("analysis started", extra={"job_id": job_id, "model_id": model_id})
        out = self._run_process(job_id, argv, work, lambda e: self._update(
            job_id, progress=float(e["progress"]), message=str(e["message"])[:255]))
        if out.rc == 0 and out.result:
            model_dir = self.storage.model_dir(model_id)
            shutil.move(work / out.result["geometry_ir"], model_dir / "geometry_ir.json")
            if out.result.get("preview_mesh"):
                shutil.move(work / out.result["preview_mesh"], model_dir / "preview_mesh.json")
            with self.db.sessions() as s:
                job = s.get(Job, job_id)
                job.state, job.progress, job.message = JobState.COMPLETED, 100.0, "Analysis complete"
                job.finished_at = datetime.now(UTC)
                model = s.get(CadModel, model_id)
                model.status, model.feature_count = ModelStatus.ANALYZED, int(out.result["feature_count"])
                s.commit()
            log.info("analysis completed", extra={"job_id": job_id, "model_id": model_id})
        else:
            self._fail_from(job_id, out, model_failed=True)
        self.storage.remove_job_dir(job_id)

    # ------------------------------------------------------------------ drawing

    def _run_drawing(self, job_id: str) -> None:
        with self.db.sessions() as s:
            job = s.get(Job, job_id)
            model = s.get(CadModel, job.model_id)
            model_id, fmt, filename = model.id, model.format, model.original_filename
            job.state, job.started_at, job.message = JobState.PLANNING, datetime.now(UTC), "Starting"
            s.commit()
        out_dir = self.storage.drawing_dir(job_id)
        argv = ["-m", "drawing_executor", "generate",
                "--geometry", str(self.storage.path("models", model_id, "geometry_ir.json")),
                "--source", str(self.storage.model_source(model_id, fmt)),
                "--settings", str(out_dir / "settings.json"), "--output-dir", str(out_dir),
                "--filename", filename, "--max-retries", str(self.settings.qa_max_retries)]
        log.info("drawing started", extra={"job_id": job_id, "model_id": model_id})
        out = self._run_process(job_id, argv, out_dir, lambda e: self._update(
            job_id, state=e.get("state", JobState.GENERATING), progress=float(e["progress"]),
            message=str(e["message"])[:255]))
        if out.rc == 0 and out.result:
            passed = bool(out.result["passed"])
            with self.db.sessions() as s:
                job = s.get(Job, job_id)
                job.finished_at = datetime.now(UTC)
                job.progress = 100.0
                if passed:
                    job.state, job.message = JobState.COMPLETED, f"Drawing complete (scale {out.result['scale']})"
                else:
                    # critical QA failures block export
                    job.state, job.error_code = JobState.FAILED, "QA_FAILED"
                    job.message = "Drawing rejected by QA"
                    job.error_message = "critical QA issues remain after repairs; see the QA report"
                s.commit()
            log.info("drawing finished passed=%s", passed, extra={"job_id": job_id})
        else:
            self._fail_from(job_id, out, model_failed=False)
