"""Detail views (RULES 1.4): features too small at the drawing scale get an enlarged, circled region."""

import json

import pytest

from drawing_executor.pipeline import generate
from drawing_planner.details import feature_point, plan_details
from drawing_qa import Rendered, validate
from drawing_schema import DrawingPlan
from drawing_schema.candidates import DimensionCandidate
from drawing_schema.compiled import CompiledDrawing
from drawing_schema.frames import view_frame
from drawing_schema.settings import DrawingSettings


@pytest.fixture(scope="module")
def shaft(geometry_files, models_dir, tmp_path_factory):
    out = tmp_path_factory.mktemp("det")
    res = generate(geometry_files["shaft"], models_dir / "shaft.step", DrawingSettings(), out)
    return res, out


def test_small_chamfers_get_detail_views(shaft, analyzed):
    res, out = shaft
    assert res.passed
    plan = DrawingPlan.model_validate_json((out / "plan.json").read_text())
    chamfers = {f.id for f in analyzed["shaft"][0].features if f.type.value == "CHAMFER"}
    assert {fid for d in plan.detail_views for fid in d.covers} == chamfers
    datums = {d.letter for d in plan.manufacturing.datums}
    assert all(d.label not in datums for d in plan.detail_views)
    cd = CompiledDrawing.model_validate_json((out / "compiled.json").read_text())
    details = [v for v in cd.views if v.detail_of]
    assert len(details) == len(plan.detail_views) and all(v.scale_factor > 1 for v in details)
    for v in details:
        letter = v.label.split(" ")[0]
        assert v.label == f"{letter} ({v.scale})"
        assert any(a.kind.value == "DETAIL_CIRCLE" and a.label == letter and a.view_id == v.detail_of
                   for a in cd.annotations)
        # geometry clipped to the circle
        r = json.loads((out / "rendered.json").read_text())["lines"][v.id]["visible"]
        c, rad = v.sheet_center, v.clip_radius * v.scale_factor
        assert r and all(((x - c[0]) ** 2 + (y - c[1]) ** 2) ** 0.5 <= rad + 1e-6 for pl in r for x, y in pl)
    compliance = json.loads((out / "compliance.json").read_text())
    assert next(i for i in compliance["items"] if i["number"] == 9)["status"] == "PASS"


def test_detail_centre_is_on_the_feature_edge(analyzed):
    ir, _ = analyzed["shaft"]
    ch = next(f for f in ir.features if f.type.value == "CHAMFER")
    p = feature_point(ir, ch.id, view_frame(__import__("drawing_schema").ViewOrientation.FRONT))
    # on the Ø20 journal's rim (radius 9-10 from the axis), not on the axis where the face centroid is
    assert 8.9 <= (p[0] ** 2 + p[1] ** 2) ** 0.5 <= 10.01


def test_no_details_when_features_are_readable(analyzed):
    from drawing_planner import plan_baseline

    ir, _ = analyzed["shaft"]
    r = plan_baseline(ir, DrawingSettings())
    chamfers = [f.id for f in ir.features if f.type.value == "CHAMFER"]
    assert plan_details(ir, r.plan, r.candidates, "1:1.5", chamfers)  # 1 mm prints as 0.67 mm
    big = [f.id for f in ir.features if f.type.value == "BOSS"]
    assert all(d.scale != "1:1.5" for d in plan_details(ir, r.plan, r.candidates, "1:1.5", big))


def test_qa_catches_a_detail_without_its_circle(shaft, analyzed):
    _, out = shaft
    plan = DrawingPlan.model_validate_json((out / "plan.json").read_text())
    cands = [DimensionCandidate.model_validate(c) for c in json.loads((out / "candidates.json").read_text())]
    cd = CompiledDrawing.model_validate_json((out / "compiled.json").read_text())
    r = json.loads((out / "rendered.json").read_text())
    rend = Rendered(lines=r["lines"], snapped=r["snapped"], hatches=r.get("hatches", {}))
    ir = analyzed["shaft"][0]
    assert not [i for i in validate(plan, cands, ir, cd, rend).issues if i.check_id == "QA-DET-001"]
    bad = cd.model_copy(update={"annotations": [a for a in cd.annotations if a.kind.value != "DETAIL_CIRCLE"]})
    assert any(i.check_id == "QA-DET-001" for i in validate(plan, cands, ir, bad, rend).issues)
