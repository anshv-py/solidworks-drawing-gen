"""Plan -> compile -> execute (OCCT HLR) -> QA -> repair loop -> export.

Progress is reported through the callback with job states PLANNING, GENERATING, VALIDATING
and EXPORTING. Exports (DXF/PDF/SVG) are written only when QA reports no CRITICAL issue;
otherwise only a clearly marked QA preview image is kept for diagnosis.

Every drawing also gets a compliance report (``compliance.json``) against the primary rule set's
Universal Mandatory Minimum. If a hard blocker fails, the sheet is stamped NOT FOR MANUFACTURE; the
drawing is still generated and downloadable, and only the explicit release step refuses it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from importlib import metadata
from pathlib import Path

from drawing_compiler import CompileOptions, LayoutError, compile_drawing
from drawing_compiler.compiler import scale_factor
from drawing_planner import plan_baseline
from drawing_planner.details import plan_details
from drawing_planner.rule_set import load_rules
from drawing_planner.view_rules import detail_triggers
from drawing_qa import INCREASE_TIER_GAP, REDUCE_SCALE, Rendered, validate
from drawing_qa.compliance import build_compliance
from drawing_schema import PlanUncertainty, scale_series
from drawing_schema.settings import DrawingSettings
from geometry_schema import GeometryIR
from geometry_service.step_analysis import read_step

from drawing_executor.dxf_writer import FONT, text_font_available, write_dxf
from drawing_executor.hlr import hidden_line_removal, section_cut, section_loops, shaded_facets
from drawing_executor.render import render
from drawing_executor.sheet import clip_to_circle, snap_extension, to_sheet

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
    releasable: bool = False


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
    rules = load_rules()
    planned = plan_baseline(ir, settings, filename=filename)
    if planned.errors:
        # user annotations that do not match this part are rejected, never silently dropped
        raise DrawingFailed("PMI_INVALID", "; ".join(planned.errors))

    def gate(p, **kw):
        return build_compliance(p.plan, ir, p.candidates, hard_blockers=rules.gate.hard_blockers,
                                stamp_text=rules.gate.stamp_text, **kw)

    defaults_applied = settings.default_gdt and not (settings.manufacturing.datums or settings.manufacturing.frames) \
        and bool(planned.plan.manufacturing.datums or planned.plan.manufacturing.frames)
    if defaults_applied and settings.sheet.scale == "AUTO":
        # the default datums / GD&T must never be the reason a drawing cannot be made: if their
        # annotations do not fit the sheet at any scale, plan again without them and say so. (With a
        # scale the user chose they are kept: the layout error then names the largest scale that fits.)
        try:
            compile_drawing(planned.plan, planned.candidates, ir,
                            CompileOptions(generated_on=generated_on, stamp=gate(planned).stamp))
        except LayoutError:
            planned = plan_baseline(ir, settings.model_copy(update={"default_gdt": False}), filename=filename)
            planned.plan = planned.plan.model_copy(update={"uncertainties": [*planned.plan.uncertainties, PlanUncertainty(
                message="default datums / GD&T omitted: their annotations do not fit on the selected sheet "
                        "(choose a larger sheet to include them)")]})
    stamp = gate(planned).stamp  # decided from the plan: the stamp is part of the layout
    (out_dir / "plan.json").write_text(planned.plan.model_dump_json(indent=2))
    (out_dir / "candidates.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in planned.candidates], indent=1)
    )

    report("GENERATING", "Importing STEP for hidden-line removal", 15)
    shape, _ = read_step(source_path)
    hlr_cache: dict[tuple, tuple] = {}

    def draw(compiled) -> Rendered:
        """OCCT hidden-line removal of every view (sections cut and hatched, details clipped), in sheet mm."""
        lines, hatches = {}, {}
        for v in compiled.views:
            key = (v.eye, v.x_axis, v.display_style.value, v.cut_point, v.cut_normal, v.model_center)
            if key not in hlr_cache:
                src, loops = shape, []
                if v.cut_point is not None:  # full section: the half behind the cutting plane, cut faces hatched
                    src = section_cut(shape, v.cut_point, v.cut_normal)
                    loops = section_loops(src, v.cut_point, v.cut_normal, v.model_center, v.eye, v.x_axis)
                hl = hidden_line_removal(src, v.model_center, v.eye, v.x_axis,
                                         with_hidden=v.display_style == "HIDDEN_LINES_VISIBLE")
                # (shaded views: the faces hide what is behind them, so only visible edges are drawn)
                hlr_cache[key] = (hl.visible, hl.hidden, loops)
            vis, hid, loops = hlr_cache[key]
            if v.clip_radius is not None:  # detail: the circular region around its centre
                vis, hid = clip_to_circle(vis, v.clip_radius), clip_to_circle(hid, v.clip_radius)
            lines[v.id] = {"visible": to_sheet(vis, v), "hidden": to_sheet(hid, v)}
            if loops:
                hatches[v.id] = [to_sheet(face, v) for face in loops]
        snapped = {}
        for d in compiled.dimensions:
            if d.kind == "LINEAR":
                polys = lines[d.view_id]["visible"] + lines[d.view_id]["hidden"]
                snapped[d.id] = tuple(snap_extension(p, d, polys) if s else p for p, s in zip((d.p1, d.p2), d.snap))
        return Rendered(lines=lines, snapped=snapped, hatches=hatches)

    opts = CompileOptions(generated_on=generated_on, stamp=stamp)
    compiled = qa = rendered = None
    iterations = 0
    best = None
    for iteration in range(1, max_retries + 2):
        iterations = iteration
        try:
            compiled = compile_drawing(planned.plan, planned.candidates, ir, opts)
        except LayoutError as exc:
            raise DrawingFailed("LAYOUT_FAILED", str(exc)) from exc
        report("GENERATING", f"Projecting views (iteration {iteration}, scale {compiled.scale})", 20 + 10 * iteration)
        rendered = draw(compiled)

        report("VALIDATING", f"Deterministic QA (iteration {iteration})", 30 + 10 * iteration)
        qa = validate(planned.plan, planned.candidates, ir, compiled, rendered, iteration=iteration)
        (out_dir / f"qa_report_{iteration}.json").write_text(qa.model_dump_json(indent=2))
        # a repair must not make the drawing worse (e.g. a smaller scale does not shrink annotation
        # text, so crowding can grow): the best iteration is kept - fewest critical, then major
        # issues, then the larger scale
        rank = (qa.critical, qa.major, -scale_factor(compiled.scale))
        if best is None or rank < best[0]:
            best = (rank, compiled, rendered, qa)
        repairs = {i.repair for i in qa.issues if i.repair and i.severity in ("CRITICAL", "MAJOR")}
        if not repairs or iteration > max_retries:
            break
        if REDUCE_SCALE in repairs:
            if settings.sheet.scale != "AUTO":
                if repairs == {REDUCE_SCALE}:
                    break  # a user-chosen scale is never changed; QA reports what does not fit
            else:
                smaller = [x for x in scale_series(settings.sheet.scale_system)
                           if scale_factor(x) < scale_factor(compiled.scale) - 1e-9]
                if not smaller:
                    break
                opts.max_scale = smaller[0]
        if INCREASE_TIER_GAP in repairs:
            opts.tier_gap += 3.0

    _, compiled, rendered, qa = best

    # RULES 1.4: detail views, now that the scale is known (kept only if QA is not worse)
    tight = {f.target.ref for f in planned.plan.manufacturing.frames
             if f.tolerance < rules.views.detail_triggers.tight_tolerance_lt_mm}
    det_triggers = detail_triggers(ir, rules, scale_factor(compiled.scale), tight) if planned.plan.rule_set else []
    wanted = sorted({fid for t in det_triggers for fid in t.feature_ids})
    details = plan_details(ir, planned.plan, planned.candidates, compiled.scale, wanted) if wanted else []
    if details:
        report("GENERATING", f"Adding {len(details)} detail view(s)", 75)
        plan2 = planned.plan.model_copy(update={"detail_views": details})
        try:
            c2 = compile_drawing(plan2, planned.candidates, ir, replace(opts, max_scale=compiled.scale, notes=[]))
            r2 = draw(c2)
            qa2 = validate(plan2, planned.candidates, ir, c2, r2, iteration=iterations + 1)
            if c2.scale == compiled.scale and (qa2.critical, qa2.major) <= (qa.critical, qa.major):
                planned.plan, compiled, rendered, qa = plan2, c2, r2, qa2
                (out_dir / "plan.json").write_text(planned.plan.model_dump_json(indent=2))
        except LayoutError:
            pass
    covered = {fid for v in compiled.views if v.detail_of
               for d in planned.plan.detail_views if d.id == v.id for fid in (d.covers or [d.feature_id])}
    det_triggers = [t.model_copy(update={"satisfied": True}) if set(t.feature_ids) <= covered else t
                    for t in det_triggers]
    (out_dir / "compiled.json").write_text(compiled.model_dump_json(indent=2))
    # what was actually drawn (sheet mm) - lets QA be re-run later without OCCT
    (out_dir / "rendered.json").write_text(json.dumps({"lines": rendered.lines, "snapped": rendered.snapped,
                                                        "hatches": rendered.hatches}))
    (out_dir / "qa_report.json").write_text(qa.model_dump_json(indent=2))
    compliance = gate(planned, qa=qa, extra_triggers=det_triggers)
    if stamp and compliance.releasable:
        compliance = compliance.model_copy(update={"stamp": stamp})
    (out_dir / "compliance.json").write_text(compliance.model_dump_json(indent=2))
    report("EXPORTING", "Writing DXF and rendering PDF/SVG/PNG", 85)
    if not text_font_available():
        raise DrawingFailed("FONT_MISSING", "no TrueType font is installed, so the drawing text cannot be rendered "
                            f"(install {FONT}, e.g. the fonts-liberation package)")
    gen = generator_id()
    dxf = out_dir / "drawing.dxf"
    shading = {}
    for v in compiled.views:
        if v.display_style == "SHADED_WITH_EDGES":
            s, (cx, cy) = v.scale_factor, v.sheet_center
            shading[v.id] = [([(cx + x * s, cy + y * s) for x, y in f.points], f.shade)
                             for f in shaded_facets(shape, v.model_center, v.eye, v.x_axis)]
    write_dxf(compiled, rendered.lines, rendered.snapped, dxf, gen, shading, rendered.hatches)
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
        "rule_set": planned.plan.rule_set,
        "releasable": compliance.releasable,
        "stamped": stamp is not None,
        "artifacts": artifacts,
        "views": {vid: {"geometry_segments": sum(len(p) - 1 for p in ls["visible"] + ls["hidden"])}
                  for vid, ls in rendered.lines.items()},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return Result(passed=qa.passed, artifacts=artifacts, qa_iterations=iterations, scale=compiled.scale,
                  releasable=compliance.releasable)
