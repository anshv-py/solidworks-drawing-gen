"""Process boundary used by the API: ``python -m geometry_service analyze ...``.

* Writes ``geometry_ir.json`` and ``preview_mesh.json`` into --output-dir.
* Emits JSON lines on the *original* stdout: {"event": "progress"|"result"|"error", ...}.
  OCCT's own console output is redirected to stderr so it cannot corrupt the protocol.
* Exit code 0 on success, 2 on invalid CAD content, 1 on internal error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

from geometry_service.errors import CadImportError


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="geometry_service")
    sub = ap.add_subparsers(dest="cmd", required=True)
    an = sub.add_parser("analyze")
    an.add_argument("--input", required=True, type=Path)
    an.add_argument("--format", required=True, choices=["STEP", "STL"])
    an.add_argument("--output-dir", required=True, type=Path)
    an.add_argument("--filename", default=None)
    an.add_argument("--no-preview", action="store_true")
    args = ap.parse_args(argv)

    proto = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)  # native library chatter -> stderr

    def emit(obj: dict) -> None:
        proto.write(json.dumps(obj) + "\n")
        proto.flush()

    try:
        from geometry_service.analyze import analyze_file  # imports OCCT lazily, inside the guard
        from shared_types import SourceFormat

        args.output_dir.mkdir(parents=True, exist_ok=True)
        ir, preview = analyze_file(
            args.input,
            SourceFormat(args.format),
            filename=args.filename,
            with_preview=not args.no_preview,
            progress=lambda msg, pct: emit({"event": "progress", "message": msg, "progress": pct}),
        )
        (args.output_dir / "geometry_ir.json").write_text(ir.model_dump_json(indent=None))
        if preview is not None:
            (args.output_dir / "preview_mesh.json").write_text(json.dumps(preview, separators=(",", ":")))
        emit(
            {
                "event": "result",
                "geometry_ir": "geometry_ir.json",
                "preview_mesh": None if preview is None else "preview_mesh.json",
                "feature_count": len(ir.features),
            }
        )
        return 0
    except CadImportError as exc:
        emit({"event": "error", "code": exc.code, "message": str(exc)})
        return 2
    except ImportError as exc:
        traceback.print_exc(file=sys.stderr)
        emit({"event": "error", "code": "GEOMETRY_ENGINE_UNAVAILABLE", "message": f"OCCT could not be loaded: {exc}"})
        return 1
    except Exception as exc:  # noqa: BLE001 - boundary: report, never crash silently
        traceback.print_exc(file=sys.stderr)
        emit({"event": "error", "code": "ANALYSIS_FAILED", "message": f"{type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
