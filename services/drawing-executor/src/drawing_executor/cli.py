"""Process boundary: ``python -m drawing_executor generate ...`` (JSON-lines protocol like geometry_service)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drawing_executor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--geometry", required=True, type=Path)
    g.add_argument("--source", required=True, type=Path)
    g.add_argument("--settings", required=True, type=Path)
    g.add_argument("--output-dir", required=True, type=Path)
    g.add_argument("--filename", default=None)
    g.add_argument("--max-retries", type=int, default=3)
    args = ap.parse_args(argv)

    proto = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)

    def emit(obj: dict) -> None:
        proto.write(json.dumps(obj) + "\n")
        proto.flush()

    try:
        from drawing_executor.pipeline import DrawingFailed, generate
        from drawing_schema.settings import DrawingSettings

        settings = DrawingSettings.model_validate_json(args.settings.read_text())
        try:
            res = generate(
                args.geometry, args.source, settings, args.output_dir, filename=args.filename,
                max_retries=args.max_retries,
                progress=lambda st, msg, pct: emit({"event": "progress", "state": st, "message": msg, "progress": pct}),
            )
        except DrawingFailed as exc:
            emit({"event": "error", "code": exc.code, "message": str(exc)})
            return 2
        emit({"event": "result", "passed": res.passed, "artifacts": res.artifacts,
              "qa_iterations": res.qa_iterations, "scale": res.scale})
        return 0
    except ImportError as exc:
        traceback.print_exc(file=sys.stderr)
        emit({"event": "error", "code": "DRAWING_ENGINE_UNAVAILABLE", "message": str(exc)})
        return 1
    except Exception as exc:  # noqa: BLE001 - process boundary
        traceback.print_exc(file=sys.stderr)
        emit({"event": "error", "code": "DRAWING_FAILED", "message": f"{type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
