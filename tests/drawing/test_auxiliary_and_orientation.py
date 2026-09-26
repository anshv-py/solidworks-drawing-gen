"""RULES 1.5 auxiliary views (arrow method) and EX 3 horizontal shafts."""

import json
import math

import pytest

from drawing_executor.pipeline import generate
from drawing_planner import plan_baseline
from drawing_qa import Rendered, validate
from drawing_schema import DrawingPlan, ViewOrientation
from drawing_schema.candidates import DimensionCandidate
from drawing_schema.compiled import CompiledDrawing
from drawing_schema.frames import view_frame
from drawing_schema.settings import DrawingSettings


def test_angled_hole_gets_an_auxiliary_view_with_its_callout(analyzed):
    ir, _ = analyzed["angled_block"]
    p = plan_baseline(ir, DrawingSettings()).plan
    [av] = p.auxiliary_views
    hole = next(f for f in ir.features if f.type.value == "HOLE")
    assert av.covers == [hole.id] and av.label not in {d.letter for d in p.manufacturing.datums}
    sel = {s.candidate_id: s.view_id for s in p.dimension_selections}
    assert sel[f"DIM-CALLOUT-{hole.id}"] == av.id
    # the entry point on the bevel is located along the two axes square to the hole (not three)
    assert sorted(k for k in sel if k.startswith(f"DIM-LOC-{hole.id}")) == [f"DIM-LOC-{hole.id}-X",
                                                                         f"DIM-LOC-{hole.id}-Y"]
    assert all(t.satisfied for t in p.view_triggers if t.kind.value == "AUXILIARY")


@pytest.fixture(scope="module")
def angled(geometry_files, models_dir, tmp_path_factory):
    out = tmp_path_factory.mktemp("aux")
    res = generate(geometry_files["angled_block"], models_dir / "angled_block.step", DrawingSettings(), out)
    return res, out


def test_auxiliary_view_is_drawn_along_the_axis(angled, analyzed):
    res, out = angled
    assert res.passed
    cd = CompiledDrawing.model_validate_json((out / "compiled.json").read_text())
    aux = next(v for v in cd.views if v.auxiliary_of)
    k = math.sqrt(0.5)
    assert aux.eye == pytest.approx((0.0, k, k))  # looking into the hole
    arrow = next(a for a in cd.annotations if a.kind.value == "VIEW_ARROW")
    assert arrow.label == aux.label and arrow.view_id == aux.auxiliary_of
    # the hole is a true circle in the auxiliary view: a centre mark there
    assert any(a.kind.value == "CENTER_MARK" and a.view_id == aux.id for a in cd.annotations)
    # and its own projection was drawn (not the parent's): the drawn extent differs from the parent's
    lines = json.loads((out / "rendered.json").read_text())["lines"]
    assert lines[aux.id]["visible"] != lines[aux.auxiliary_of]["visible"]


def test_qa_catches_an_auxiliary_view_without_its_arrow(angled, analyzed):
    _, out = angled
    plan = DrawingPlan.model_validate_json((out / "plan.json").read_text())
    cands = [DimensionCandidate.model_validate(c) for c in json.loads((out / "candidates.json").read_text())]
    cd = CompiledDrawing.model_validate_json((out / "compiled.json").read_text())
    r = json.loads((out / "rendered.json").read_text())
    rend = Rendered(lines=r["lines"], snapped=r["snapped"], hatches=r.get("hatches", {}))
    bad = cd.model_copy(update={"annotations": [a for a in cd.annotations if a.kind.value != "VIEW_ARROW"]})
    assert any(i.check_id == "QA-AUX-001" for i in validate(plan, cands, analyzed["angled_block"][0], bad, rend).issues)


@pytest.mark.parametrize("name", ["shaft", "keyed_shaft", "cylindrical_part"])
def test_shafts_are_drawn_horizontal(analyzed, name):
    ir, _ = analyzed[name]
    p = plan_baseline(ir, DrawingSettings()).plan
    boss = max((f for f in ir.features if f.type.value == "BOSS"), key=lambda b: b.diameter)
    front = view_frame(ViewOrientation.FRONT, p.view_frame)
    assert abs(abs(sum(a * b for a, b in zip(front.x, boss.axis.direction))) - 1) < 1e-6
    # manual views keep the user's frame
    assert plan_baseline(ir, DrawingSettings(view_selection="MANUAL")).plan.view_frame.value == "Z_UP"


def test_long_shaft_gets_a_conventional_break(analyzed):
    ir, _ = analyzed["long_shaft"]
    p = plan_baseline(ir, DrawingSettings()).plan
    [b] = p.breaks
    # inside the 250 mm journal, keeping max(D, 15 %) at each end
    assert (b.start[2], b.end[2]) == pytest.approx((50 + 37.5, 300 - 37.5))
    assert all(t.satisfied for t in p.view_triggers if t.kind.value == "BREAK")
    # a short shaft is not broken
    assert plan_baseline(analyzed["shaft"][0], DrawingSettings()).plan.breaks == []


def test_break_shortens_the_view_and_dimensions_keep_true_values(geometry_files, models_dir, tmp_path):
    res = generate(geometry_files["long_shaft"], models_dir / "long_shaft.step", DrawingSettings(), tmp_path)
    assert res.passed  # QA measured every dimension back across the break
    cd = CompiledDrawing.model_validate_json((tmp_path / "compiled.json").read_text())
    front = next(v for v in cd.views if v.break_at)
    ua, ub, gap = front.break_at
    assert front.outline.w / front.scale_factor == pytest.approx(300 - (ub - ua) + gap)
    overall = next(d for d in cd.dimensions if d.text == "300.00")
    assert abs(overall.p2[0] - overall.p1[0]) / front.scale_factor < 300  # drawn short, printed true
    lines = json.loads((tmp_path / "rendered.json").read_text())["lines"][front.id]["visible"]
    cx, s = front.sheet_center[0], front.scale_factor
    assert not [p for pl in lines for p in pl if ua * s + 1e-3 < p[0] - cx < (ua + gap) * s - 1e-3]
