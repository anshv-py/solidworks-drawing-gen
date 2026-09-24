"""Entry point: analyse a CAD file into GeometryIR (+ preview mesh)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from geometry_schema import GeometryIR
from shared_types import SourceFormat

Progress = Callable[[str, float], None]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def analyze_file(
    path: Path,
    fmt: SourceFormat,
    *,
    filename: str | None = None,
    with_preview: bool = True,
    progress: Progress | None = None,
) -> tuple[GeometryIR, dict | None]:
    report = progress or (lambda msg, pct: None)
    meta = dict(filename=filename or path.name, sha256=sha256_of(path), size_bytes=path.stat().st_size)
    if fmt == SourceFormat.STEP:
        from geometry_service.mesh import brep_preview
        from geometry_service.step_analysis import analyze_step, read_step

        ir = analyze_step(path, progress=report, **meta)
        preview = None
        if with_preview:
            report("Tessellating preview", 97)
            preview = brep_preview(read_step(path)[0], ir)
        return ir, preview
    if fmt == SourceFormat.STL:
        from geometry_service.mesh import stl_preview
        from geometry_service.stl_analysis import analyze_stl, read_stl

        ir = analyze_stl(path, progress=report, **meta)
        preview = stl_preview(*read_stl(path)) if with_preview else None
        return ir, preview
    raise ValueError(f"unsupported format {fmt}")
