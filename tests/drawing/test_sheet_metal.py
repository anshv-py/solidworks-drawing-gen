"""Sheet metal (EX 5): bend recognition, DIN 6935 flat pattern, flat-pattern view, QA."""

import json
import math

import pytest

from drawing_executor.pipeline import generate
from drawing_planner import plan_baseline
from drawing_planner.flat_pattern import compute_flat_pattern, din6935_k
from drawing_qa import Rendered, validate
from drawing_schema import DrawingPlan
from drawing_schema.candidates import DimensionCandidate
from drawing_schema.compiled import CompiledDrawing
from drawing_schema.settings import DrawingSettings


def test_bend_recognition_matches_the_model(analyzed, manifest):
    ir, _ = analyzed["sheet_bracket"]
    exp = manifest["models"]["sheet_bracket"]["expected"]["sheet_metal"]
    assert ir.sheet_metal is not None and ir.sheet_metal.thickness == pytest.approx(exp["thickness"])
    [b] = [f for f in ir.features if f.type == "BEND"]
    assert (b.inner_radius, b.angle_deg) == pytest.approx((exp["bends"][0]["inner_radius"], exp["bends"][0]["angle_deg"]))
    assert not [f for f in ir.features if f.type == "FILLET"]  # the bend faces are not fillets


@pytest.mark.parametrize("name", ["bracket", "chamfered_block", "mounting_plate", "shaft", "flange"])
def test_machined_parts_are_not_sheet_metal(analyzed, name):
    assert analyzed[name][0].sheet_metal is None


def test_din_6935_neutral_fibre():
    assert din6935_k(2, 2) == pytest.approx(0.65)
    assert din6935_k(4, 2) == pytest.approx(0.65 + 0.5 * math.log10(2))
    assert din6935_k(12, 2) == 1.0


def test_flat_pattern_developed_size_and_holes(analyzed, manifest):
    ir, _ = analyzed["sheet_bracket"]
    exp = manifest["models"]["sheet_bracket"]["expected"]["sheet_metal"]
    fp, why = compute_flat_pattern(ir)
    assert why == "" and fp.length == pytest.approx(exp["flat_length"]) and fp.width == pytest.approx(exp["flat_width"])
    [b] = fp.bends
    assert b.up and b.x == pytest.approx(56 + b.allowance / 2)
    xs = sorted({round(x, 6) for x, _, _, _ in fp.holes})
    assert xs == pytest.approx([20.0, 56 + b.allowance + 21.0])  # 60-40 from the free end; 25-4 past the bend
    assert compute_flat_pattern(analyzed["shaft"][0])[0] is None


def test_plan_has_flat_pattern_notes_and_bend_callout(analyzed):
    ir, _ = analyzed["sheet_bracket"]
    r = plan_baseline(ir, DrawingSettings())
    p = r.plan
    assert p.flat_pattern is not None and len(p.flat_pattern.bends) == 1
    assert any(t.kind.value == "FLAT_PATTERN" and t.satisfied for t in p.view_triggers)
    assert any("DIN 6935" in n for n in p.rule_notes) and any("BEND ANGLES ±0.5°" in n for n in p.rule_notes)
    sel = {s.candidate_id: s.view_id for s in p.dimension_selections}
    assert sel["DIM-FLAT-L"] == sel["DIM-FLAT-W"] == "V-FLAT"
    bend = next(c for c in r.candidates if c.id.startswith("DIM-BEND-"))
    assert bend.text == "BEND R2.00 90°" and sel[bend.id] != "V-FLAT"


@pytest.fixture(scope="module")
def drawn(geometry_files, models_dir, tmp_path_factory):
    out = tmp_path_factory.mktemp("sm")
    res = generate(geometry_files["sheet_bracket"], models_dir / "sheet_bracket.step", DrawingSettings(), out)
    return res, out


def test_flat_pattern_view_is_drawn_where_its_dimensions_are(drawn):
    res, out = drawn
    assert res.passed
    cd = CompiledDrawing.model_validate_json((out / "compiled.json").read_text())
    flat = next(v for v in cd.views if v.flat_lines)
    assert flat.label == "FLAT PATTERN"
    lines = json.loads((out / "rendered.json").read_text())["lines"][flat.id]["visible"]
    xs = [p[0] for pl in lines for p in pl]
    length = next(d for d in cd.dimensions if d.id == "DIM-FLAT-L")
    assert min(xs) == pytest.approx(min(length.p1[0], length.p2[0]), abs=1e-3)  # outline and dimension agree
    bend = next(a for a in cd.annotations if a.kind.value == "BEND_LINE")
    assert bend.label == "UP 90° R2.00"


def test_qa_catches_a_missing_bend_line(drawn, analyzed):
    _, out = drawn
    plan = DrawingPlan.model_validate_json((out / "plan.json").read_text())
    cands = [DimensionCandidate.model_validate(c) for c in json.loads((out / "candidates.json").read_text())]
    cd = CompiledDrawing.model_validate_json((out / "compiled.json").read_text())
    r = json.loads((out / "rendered.json").read_text())
    rend = Rendered(lines=r["lines"], snapped=r["snapped"], hatches=r.get("hatches", {}))
    bad = cd.model_copy(update={"annotations": [a for a in cd.annotations if a.kind.value != "BEND_LINE"]})
    assert any(i.check_id == "QA-FLAT-001" for i in validate(plan, cands, analyzed["sheet_bracket"][0], bad, rend).issues)
