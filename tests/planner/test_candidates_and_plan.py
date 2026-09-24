"""Planner: candidate values must equal GeometryIR fields; plan selections must be sound."""

import pytest

from drawing_planner import generate_candidates, plan_baseline, remove_redundant
from drawing_schema import ViewFrame, ViewOrientation
from drawing_schema.candidates import CandidateKind, CandidateRole
from drawing_schema.settings import DrawingSettings

MODELS = ["plate_with_holes", "mounting_plate", "pocketed_block", "bracket", "shaft", "flange",
          "cylindrical_part", "enclosure", "chamfered_block"]


def texts(cands):
    return {c.text for c in cands}


def test_values_are_copied_from_geometry(analyzed):
    ir, _ = analyzed["plate_with_holes"]
    c = {x.id: x for x in generate_candidates(ir, trailing_zeros=False)}
    assert c["DIM-OVERALL-X"].value == ir.bounding_box.size[0]
    callouts = [x for x in c.values() if x.kind == CandidateKind.HOLE_CALLOUT]
    assert {x.text for x in callouts} == {"4X Ø8 THRU", "Ø20 THRU"}
    for x in c.values():
        assert x.source  # every value names the GeometryIR field it came from


@pytest.mark.parametrize("name,expected", [
    ("plate_with_holes", {"120", "80", "10", "4X Ø8 THRU", "Ø20 THRU", "50", "90", "15", "60", "40"}),
    ("flange", {"40", "Ø100", "Ø45", "8X Ø8 THRU EQ SP", "Ø86", "Ø20 THRU"}),
    ("mounting_plate", {"150", "100", "8", "3X Ø6.6 THRU", "2X Ø6.6 THRU\nCBORE Ø11 DEPTH 4", "2X 40", "4X R10"}),
    ("pocketed_block", {"100", "60", "30", "50", "Ø6 DEPTH 15"}),
    ("bracket", {"80", "50", "60", "2X Ø9 THRU", "R5", "10", "40"}),
    ("shaft", {"140", "Ø30", "Ø20", "40", "2X 1 X 45°"}),
    ("chamfered_block", {"60", "40", "20", "3 X 45°", "R4"}),
])
def test_expected_labels(analyzed, name, expected):
    ir, _ = analyzed[name]
    assert expected <= texts(generate_candidates(ir, trailing_zeros=False))


def test_trailing_zeros_follow_decimal_places(analyzed):
    # default: every value printed with the drawing's decimal places (as in the reference drawings)
    t = texts(generate_candidates(analyzed["mounting_plate"][0]))
    assert {"150.00", "3X Ø6.60 THRU", "2X Ø6.60 THRU\nCBORE Ø11.00 DEPTH 4.00", "4X R10.00"} <= t


def test_turned_part_uses_diameter_instead_of_overall_width(analyzed):
    ids = {c.id for c in generate_candidates(analyzed["flange"][0])}
    assert "DIM-OVERALL-X" not in ids and "DIM-OVERALL-Y" not in ids and "DIM-OVERALL-Z" in ids


def test_shaft_step_length_includes_end_chamfer(analyzed):
    ir, _ = analyzed["shaft"]
    steps = [c for c in generate_candidates(ir) if c.id.startswith("DIM-HEIGHT")]
    assert sorted(round(c.value, 6) for c in steps) == [40.0, 40.0, 60.0]
    assert all("distance_1" in c.source for c in steps if c.value == 40.0)


def test_redundant_chain_is_broken(analyzed):
    ir, _ = analyzed["flange"]
    kept, dropped = remove_redundant(generate_candidates(ir))
    heights = [c for c in kept if c.id.startswith("DIM-HEIGHT")] + [c for c in kept if c.id == "DIM-OVERALL-Z"]
    assert len(heights) == 2  # 10 + 30 = 40: one link of the closed chain is dropped
    assert any(c.id.startswith("DIM-HEIGHT") for c in dropped)


def test_coincident_centre_and_face_are_not_a_chain(analyzed):
    # bracket: slot end (face) and a hole centre share x = 20 - both location dims must survive
    r = plan_baseline(analyzed["bracket"][0], DrawingSettings())
    selected = {s.candidate_id for s in r.plan.dimension_selections}
    by_id = {c.id: c for c in r.candidates}
    xs = sorted(by_id[i].value for i in selected if i.startswith("DIM-LOC-HOLE") and i.endswith("-X"))
    assert xs == [20.0, 60.0]


@pytest.mark.parametrize("name", MODELS)
def test_plan_is_valid_and_views_show_true_size(analyzed, name):
    from drawing_schema.frames import dot, view_frame

    ir, _ = analyzed[name]
    r = plan_baseline(ir, DrawingSettings())
    plan = r.plan
    assert plan.primary_view.orientation == ViewOrientation.ISOMETRIC and not plan.primary_view.dimensioned
    by_id = {c.id: c for c in r.candidates}
    for s in plan.dimension_selections:
        c = by_id[s.candidate_id]
        f = view_frame(ViewOrientation(s.view_id.removeprefix("V-")), plan.view_frame)
        if c.direction is not None and c.kind == CandidateKind.LINEAR:
            assert abs(dot(c.direction, f.eye)) < 1e-6, (name, c.id)
        if c.kind in (CandidateKind.HOLE_CALLOUT, CandidateKind.PCD, CandidateKind.RADIUS):
            assert abs(dot(c.axis, f.eye)) > 1 - 1e-6, (name, c.id)
    assert len({s.candidate_id for s in plan.dimension_selections}) == len(plan.dimension_selections)


def test_preferences_filter_categories(analyzed):
    ir, _ = analyzed["plate_with_holes"]
    s = DrawingSettings.model_validate({"dimensions": {"holes": False}})
    r = plan_baseline(ir, s)
    kinds = {next(c for c in r.candidates if c.id == x.candidate_id).kind for x in r.plan.dimension_selections}
    assert CandidateKind.HOLE_CALLOUT not in kinds


def test_y_up_frame_puts_front_on_xy_plane(analyzed):
    ir, _ = analyzed["plate_with_holes"]
    r = plan_baseline(ir, DrawingSettings(view_frame=ViewFrame.Y_UP))
    by_id = {c.id: c for c in r.candidates}
    # in the Y_UP (SolidWorks) frame the plate's 80 mm Y extent is the FRONT view's height
    views = {s.candidate_id: s.view_id for s in r.plan.dimension_selections}
    assert views["DIM-OVERALL-Y"] == "V-FRONT" and by_id["DIM-OVERALL-Y"].value == 80


def test_engineering_information_stays_unspecified(analyzed):
    r = plan_baseline(analyzed["flange"][0], DrawingSettings())
    assert all(f.status == "UNSPECIFIED" for _, f in r.plan.engineering_information)
    assert r.plan.drawing_kind == "GEOMETRY"
    assert "no LLM" in r.plan.rationale
