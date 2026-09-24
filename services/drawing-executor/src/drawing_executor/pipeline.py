"""Plan -> compile -> execute (OCCT HLR) -> QA -> repair loop -> export.

Progress is reported through the callback with job states PLANNING, GENERATING, VALIDATING
and EXPORTING. Exports (DXF/PDF/SVG) are written only when QA reports no CRITICAL issue;
otherwise only a clearly marked QA preview image is kept for diagnosis.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from importlib import metadata
from pathlib import Path

from drawing_compiler import CompileOptions, LayoutError, compile_drawing
from drawing_planner import plan_baseline
from drawing_qa import INCREASE_TIER_GAP, REDUCE_SCALE, Rendered, validate
from drawing_schema import ISO_5455_SCALES
from drawing_schema.settings import DrawingSettings
from geometry_schema import GeometryIR
from geometry_service.step_analysis import read_step

from drawing_executor.dxf_writer import write_dxf
from drawing_executor.hlr import hidden_line_removal
from drawing_executor.render import render
from drawing_executor.sheet import snap_extension, to_sheet

Progress = Callable[[str, str, float], None]  # (state, message, percent)


class DrawingFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Result:
    passed: bool
    artifacts: dict[str, str]
    qa_iterations: int
    scale: str


def generator_id() -> str:
    return f"OCCT HLR ({_v('cadquery-ocp')}) + ezdxf {_v('ezdxf')} + matplotlib {_v('matplotlib')}"


def _v(dist: str) -> str:
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return "?"


def generate(
    geometry_path: Path,
    source_path: Path,
    settings: DrawingSettings,
    out_dir: Path,
    *,
    filename: str | None = None,
    max_retries: int = 3,
    progress: Progress | None = None,
    generated_on: date | None = None,
) -> Result:
    report = progress or (lambda state, msg, pct: None)
    out_dir.mkdir(parents=True, exist_ok=True)
    ir = GeometryIR.model_validate_json(geometry_path.read_text())
    if ir.representation != "EXACT_BREP":
        raise DrawingFailed(
            "STL_NOT_SUPPORTED",
            "drawing generation needs exact B-Rep geometry (STEP); STL meshes are not supported yet",
        )

    report("PLANNING", "Selecting views and dimensions", 5)
    planned = plan_baseline(ir, settings, filename=filename)
    (out_dir / "plan.json").write_text(planned.plan.model_dump_json(indent=2))
    (out_dir / "candidates.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in planned.candidates], indent=1)
    )

    report("GENERATING", "Importing STEP for hidden-line removal", 15)
    shape, _ = read_step(source_path)
    hlr_cache: dict[tuple, tuple] = {}
    opts = CompileOptions(generated_on=generated_on)
    compiled = qa = rendered = None
    iterations = 0
    for iteration in range(1, max_retries + 2):
        iterations = iteration
        try:
            compiled = compile_drawing(planned.plan, planned.candidates, ir, opts)
        except LayoutError as exc:
            raise DrawingFailed("LAYOUT_FAILED", str(exc)) from exc
        report("GENERATING", f"Projecting views (iteration {iteration}, scale {compiled.scale})", 20 + 10 * iteration)
        lines = {}
        for v in compiled.views:
            key = (v.orientation.value, v.display_style.value)
            if key not in hlr_cache:
                hl = hidden_line_removal(shape, v.model_center, v.eye, v.x_axis,
                                         with_hidden=v.display_style == "HIDDEN_LINES_VISIBLE")
                hlr_cache[key] = (hl.visible, hl.hidden)
            vis, hid = hlr_cache[key]
            lines[v.id] = {"visible": to_sheet(vis, v), "hidden": to_sheet(hid, v)}
        snapped = {}
        for d in compiled.dimensions:
            if d.kind == "LINEAR":
                polys = lines[d.view_id]["visible"] + lines[d.view_id]["hidden"]
                snapped[d.id] = tuple(snap_extension(p, d, polys) if s else p for p, s in zip((d.p1, d.p2), d.snap))
        rendered = Rendered(lines=lines, snapped=snapped)

        report("VALIDATING", f"Deterministic QA (iteration {iteration})", 30 + 10 * iteration)
        qa = validate(planned.plan, planned.candidates, ir, compiled, rendered, iteration=iteration)
        (out_dir / f"qa_report_{iteration}.json").write_text(qa.model_dump_json(indent=2))
        repairs = {i.repair for i in qa.issues if i.repair and i.severity in ("CRITICAL", "MAJOR")}
        if not repairs or iteration > max_retries:
            break
        if REDUCE_SCALE in repairs:
            idx = ISO_5455_SCALES.index(compiled.scale)
            if idx + 1 >= len(ISO_5455_SCALES):
                break
            opts.max_scale = ISO_5455_SCALES[idx + 1]
        if INCREASE_TIER_GAP in repairs:
            opts.tier_gap += 3.0

    (out_dir / "compiled.json").write_text(compiled.model_dump_json(indent=2))
    # what was actually drawn (sheet mm) - lets QA be re-run later without OCCT
    (out_dir / "rendered.json").write_text(json.dumps({"lines": rendered.lines, "snapped": rendered.snapped}))
    (out_dir / "qa_report.json").write_text(qa.model_dump_json(indent=2))
    report("EXPORTING", "Writing DXF and rendering PDF/SVG/PNG", 85)
    gen = generator_id()
    dxf = out_dir / "drawing.dxf"
    write_dxf(compiled, rendered.lines, rendered.snapped, dxf, gen)
    artifacts: dict[str, str] = {}
    if qa.passed:
        render(dxf, compiled.sheet_w, compiled.sheet_h,
               {"pdf": out_dir / "drawing.pdf", "svg": out_dir / "drawing.svg", "png": out_dir / "preview.png"})
        artifacts = {"dxf": "drawing.dxf", "pdf": "drawing.pdf", "svg": "drawing.svg", "png": "preview.png"}
    else:
        # critical QA failure: no deliverables, only a diagnostic preview
        render(dxf, compiled.sheet_w, compiled.sheet_h, {"png": out_dir / "preview_failed_qa.png"})
        dxf.rename(out_dir / "rejected_drawing.dxf")
        artifacts = {"png": "preview_failed_qa.png"}
    manifest = {
        "generator": gen,
        "solidworks": False,
        "qa_passed": qa.passed,
        "qa_iterations": iterations,
        "scale": compiled.scale,
        "artifacts": artifacts,
        "views": {vid: {"geometry_segments": sum(len(p) - 1 for p in ls["visible"] + ls["hidden"])}
                  for vid, ls in rendered.lines.items()},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return Result(passed=qa.passed, artifacts=artifacts, qa_iterations=iterations, scale=compiled.scale)
