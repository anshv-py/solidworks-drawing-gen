"""Job execution.

``LocalProcessRunner`` runs jobs on a thread pool; each CAD analysis runs in its
own subprocess (``python -m geometry_service analyze``) with a timeout and an
address-space limit, so a malformed file cannot crash or exhaust the API
process. A Redis/RQ runner with the same ``submit`` interface is planned for
multi-host deployment.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Protocol

from cad_api.config import Settings
from cad_api.db import CadModel, Database, Job, JobState, ModelStatus
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


class LocalProcessRunner:
    def __init__(self, settings: Settings, db: Database, storage: Storage) -> None:
        self.settings, self.db, self.storage = settings, db, storage
        self.pool = ThreadPoolExecutor(max_workers=settings.job_workers, thread_name_prefix="job")
        self._lock = threading.Lock()

    def submit(self, job_id: str) -> None:
        self.pool.submit(self._run_safely, job_id)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=False)

    # ------------------------------------------------------------------ internals

    def _update(self, job_id: str, **fields) -> None:
        with self.db.sessions() as s:
            job = s.get(Job, job_id)
            for k, v in fields.items():
                setattr(job, k, v)
            s.commit()

    def _run_safely(self, job_id: str) -> None:
        try:
            self._run_analysis(job_id)
        except Exception as exc:  # noqa: BLE001 - never lose a job silently
            log.exception("job crashed", extra={"job_id": job_id})
            self._fail(job_id, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")

    def _fail(self, job_id: str, code: str, message: str) -> None:
        with self.db.sessions() as s:
            job = s.get(Job, job_id)
            job.state, job.error_code, job.error_message = JobState.FAILED, code, message[:2000]
            job.finished_at = datetime.now(UTC)
            model = s.get(CadModel, job.model_id)
            model.status = ModelStatus.FAILED
            s.commit()

    def _run_analysis(self, job_id: str) -> None:
        with self.db.sessions() as s:
            job = s.get(Job, job_id)
            model = s.get(CadModel, job.model_id)
            model_id, fmt, filename = model.id, model.format, model.original_filename
            job.state, job.started_at, job.message = JobState.ANALYZING, datetime.now(UTC), "Starting analysis"
            model.status = ModelStatus.ANALYZING
            s.commit()

        work = self.storage.job_dir(job_id)
        src = self.storage.model_source(model_id, fmt)
        cmd = [
            self.settings.analysis_python, "-m", "geometry_service", "analyze",
            "--input", str(src), "--format", fmt, "--output-dir", str(work), "--filename", filename,
        ]
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "HOME": str(work),
            "OMP_NUM_THREADS": "1",
        }
        preexec = (
            _limit_resources(self.settings.analysis_memory_mb * 1024 * 1024)
            if sys.platform.startswith("linux")
            else None
        )
        log.info("analysis started", extra={"job_id": job_id, "model_id": model_id})
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=work, env=env,
            text=True, preexec_fn=preexec,  # noqa: PLW1509
        )
        killed = threading.Event()

        def kill() -> None:
            killed.set()
            proc.kill()

        timer = threading.Timer(self.settings.analysis_timeout_s, kill)
        timer.start()
        result: dict | None = None
        error: dict | None = None
        stderr_tail: list[str] = []

        def drain_stderr() -> None:
            for line in proc.stderr:  # keep only a bounded tail for diagnostics
                stderr_tail.append(line)
                del stderr_tail[:-40]

        t_err = threading.Thread(target=drain_stderr, daemon=True)
        t_err.start()
        try:
            for line in proc.stdout:
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if evt.get("event") == "progress":
                    self._update(job_id, progress=float(evt["progress"]), message=str(evt["message"])[:255])
                elif evt.get("event") == "result":
                    result = evt
                elif evt.get("event") == "error":
                    error = evt
            rc = proc.wait()
        finally:
            timer.cancel()
            t_err.join(timeout=5)

        if rc == 0 and result:
            model_dir = self.storage.model_dir(model_id)
            shutil.move(work / result["geometry_ir"], model_dir / "geometry_ir.json")
            if result.get("preview_mesh"):
                shutil.move(work / result["preview_mesh"], model_dir / "preview_mesh.json")
            with self.db.sessions() as s:
                job = s.get(Job, job_id)
                job.state, job.progress, job.message = JobState.COMPLETED, 100.0, "Analysis complete"
                job.finished_at = datetime.now(UTC)
                model = s.get(CadModel, model_id)
                model.status, model.feature_count = ModelStatus.ANALYZED, int(result["feature_count"])
                s.commit()
            self.storage.remove_job_dir(job_id)
            log.info("analysis completed", extra={"job_id": job_id, "model_id": model_id})
            return
        if error:
            self._fail(job_id, error.get("code", "ANALYSIS_FAILED"), error.get("message", "analysis failed"))
        elif killed.is_set():
            self._fail(job_id, "ANALYSIS_TIMEOUT", f"analysis exceeded {self.settings.analysis_timeout_s}s")
        elif rc < 0:
            self._fail(job_id, "ANALYSIS_KILLED", f"analysis process terminated by signal {-rc} (e.g. memory limit)")
        else:
            self._fail(job_id, "ANALYSIS_CRASHED", f"analysis process exited with code {rc}")
        log.warning("analysis failed rc=%s stderr_tail=%s", rc, "".join(stderr_tail)[-2000:],
                    extra={"job_id": job_id})
        self.storage.remove_job_dir(job_id)

