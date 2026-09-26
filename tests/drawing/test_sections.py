"""Section views (RULES 1.3, ISO 128-44 / 128-50): planned from the triggers, drawn in place of a view,
hatched, the cutting plane shown in another view - and checked by QA."""

import json

import ezdxf
import pytest

from drawing_executor.pipeline import generate
from drawing_planner import plan_baseline
from drawing_qa import Rendered, validate
from drawing_schema import DrawingPlan
from drawing_schema.candidates import DimensionCandidate
from drawing_schema.compiled import CompiledDrawing
from drawing_schema.settings import DrawingSettings
from geometry_schema import GeometryIR


def test_section_is_planned_through_the_triggering_feature(analyzed):
    ir, _ = analyzed["cylindrical_part"]
    p = plan_baseline(ir, DrawingSettings()).plan
    [sec] = p.sections
    blind = next(f for f in ir.features if getattr(f, "through", True) is False)
    assert sec.replaces.value == "FRONT" and sec.id == "V-FRONT" and sec.plane.through_feature_id == blind.id
    assert sec.parent_view_id != sec.id
    assert all(t.satisfied for t in p.view_triggers if t.kind.value == "SECTION")
    # manual views: no sections are added
    assert plan_baseline(ir, DrawingSettings(view_selection="MANUAL")).plan.sections == []


def test_one_section_serves_every_feature_in_its_plane(analyzed):
    p = plan_baseline(analyzed["mounting_plate"][0], DrawingSettings()).plan
    secs = [t for t in p.view_triggers if t.kind.value == "SECTION"]
    assert len(p.sections) == 1 and len(secs) == 2 and all(t.satisfied for t in secs)  # both counterbores


@pytest.fixture(scope="module")
def drawn(geometry_files, models_dir, tmp_path_factory):
    out = tmp_path_factory.mktemp("sec")
    res = generate(geometry_files["pocketed_block"], models_dir / "pocketed_block.step", DrawingSettings(), out)
    return res, out


def test_section_is_drawn_hatched_and_indicated(drawn):
    res, out = drawn
    assert res.passed
    cd = CompiledDrawing.model_validate_json((out / "compiled.json").read_text())
    sec = next(v for v in cd.views if v.cut_point is not None)
    plan = DrawingPlan.model_validate_json((out / "plan.json").read_text())
    letter = plan.sections[0].label
    assert letter not in {d.letter for d in plan.manufacturing.datums}  # never a datum letter
    assert sec.label == f"{letter}-{letter}" and sec.display_style.value == "HIDDEN_LINES_REMOVED"
    line = next(a for a in cd.annotations if a.kind.value == "SECTION_LINE")
    assert line.label == letter and line.view_id != sec.id and len(line.points) == 4
    rendered = json.loads((out / "rendered.json").read_text())
    assert rendered["hatches"][sec.id]  # cut faces found in the plane
    assert not rendered["lines"][sec.id]["hidden"]  # no hidden lines in a section
    doc = ezdxf.readfile(out / "drawing.dxf")
    hatches = doc.modelspace().query("HATCH[layer=='HATCH']")
    assert len(hatches) >= 1 and all(h.dxf.pattern_name == "ANSI31" for h in hatches)
    assert len(doc.modelspace().query("*[layer=='CUTTING']")) == 2  # the two thick ends
    compliance = json.loads((out / "compliance.json").read_text())
    assert next(i for i in compliance["items"] if i["number"] == 9)["status"] == "PASS"


def test_qa_catches_a_section_without_its_cutting_plane_or_hatching(drawn, analyzed):
    _, out = drawn
    plan = DrawingPlan.model_validate_json((out / "plan.json").read_text())
    cands = [DimensionCandidate.model_validate(c) for c in json.loads((out / "candidates.json").read_text())]
    cd = CompiledDrawing.model_validate_json((out / "compiled.json").read_text())
    r = json.loads((out / "rendered.json").read_text())
    ir: GeometryIR = analyzed["pocketed_block"][0]
    ok = validate(plan, cands, ir, cd, Rendered(lines=r["lines"], snapped=r["snapped"], hatches=r["hatches"]))
    assert not [i for i in ok.issues if i.check_id == "QA-SEC-001"]
    no_line = cd.model_copy(update={"annotations": [a for a in cd.annotations if a.kind.value != "SECTION_LINE"]})
    bad = validate(plan, cands, ir, no_line, Rendered(lines=r["lines"], snapped=r["snapped"], hatches=r["hatches"]))
    assert any(i.check_id == "QA-SEC-001" and i.severity.value == "CRITICAL" for i in bad.issues)
    bad = validate(plan, cands, ir, cd, Rendered(lines=r["lines"], snapped=r["snapped"], hatches={}))
    assert any(i.check_id == "QA-SEC-001" and "hatched" in i.message for i in bad.issues)
