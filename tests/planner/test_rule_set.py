"""Primary drawing rule set (drawing_planner/rules): roles, treatments, view rules, compliance gate."""

import pytest

from drawing_planner import plan_baseline
from drawing_planner.iso286 import UnsupportedFit, deviations
from drawing_planner.roles import PartFamily, infer_roles
from drawing_planner.rule_set import RULES_DIR, load_rules
from drawing_qa.compliance import build_compliance
from drawing_schema import PICTORIAL, ViewOrientation
from drawing_schema.pmi import ToleranceKind
from drawing_schema.roles import FeatureRole, RoleOverride, RoleSource
from drawing_schema.settings import DrawingSettings

R = load_rules()


def plan(analyzed, name, **settings):
    ir, _ = analyzed[name]
    return ir, plan_baseline(ir, DrawingSettings.model_validate(settings), filename=f"{name}.step")


def roles_of(analyzed, name, overrides=None):
    return infer_roles(analyzed[name][0], R, overrides)


def test_rule_set_and_source_documents_ship_together():
    assert R.label.startswith("CADAI-MFG-RULES")
    assert R.defaults.general_tolerance == "ISO 2768-mK" and R.defaults.default_surface_finish_ra == 3.2
    assert set(R.gate.hard_blockers) == {1, 2, 3, 4, 5, 6, 7, 8, 11}
    rules = (RULES_DIR / "manufacturing_drawing_rules.md").read_text(encoding="utf-8")
    examples = (RULES_DIR / "manufacturing_drawing_reference_examples.md").read_text(encoding="utf-8")
    assert "## 4. GD&T Logic (Feature Control Frame Decision Tree)" in rules
    assert "## 1. Universal Mandatory Minimum" in examples and "## 7. Cross-Part Pattern Library" in examples


@pytest.mark.parametrize("size,cls,expected", [
    (40, "H7", (0.025, 0.0)), (20, "h6", (0.0, -0.013)), (24, "h6", (0.0, -0.013)), (20, "g6", (-0.007, -0.020)),
    (30, "H8", (0.033, 0.0)), (5, "H7", (0.012, 0.0)), (25, "k6", (0.015, 0.002)), (25, "p6", (0.035, 0.022)),
    (50, "f7", (-0.025, -0.050)), (30, "H7", (0.021, 0.0)),  # 30 belongs to "over 18 up to 30"
])
def test_iso_286_deviations(size, cls, expected):
    assert deviations(size, cls) == pytest.approx(expected)


def test_unsupported_fits_are_refused_not_guessed():
    for size, cls in ((20, "s6"), (600, "H7"), (20, "X7")):
        with pytest.raises(UnsupportedFit):
            deviations(size, cls)


def test_iso_273_clearance_match():
    cl = R.roles.inference.clearance_holes
    assert cl.match(6.6) == ("M6", 6.0) and cl.match(9.0) == ("M8", 8.0) and cl.match(3.2) == ("M3", 3.0)
    assert cl.match(7.7) is None


def test_roles_follow_the_pattern_library(analyzed):
    shaft = roles_of(analyzed, "shaft")
    assert shaft.family == PartFamily.SHAFT
    assert [a.role for a in shaft.assignments].count(FeatureRole.BEARING_SEAT) == 2  # both Ø20 journals (EX 3)
    assert [a.role for a in shaft.assignments].count(FeatureRole.SHOULDER_FACE) == 2
    flange = {a.role for a in roles_of(analyzed, "flange").assignments}
    assert {FeatureRole.MOUNTING_FACE, FeatureRole.CENTRAL_BORE, FeatureRole.CLEARANCE_HOLES} <= flange
    plate = roles_of(analyzed, "mounting_plate")
    assert all(a.role != FeatureRole.DOWEL_HOLE for a in plate.assignments)
    assert any("ISO 273 clearance hole for M6" in r for a in plate.assignments for r in a.reasons)
    # every guess is an assumption with its reasons
    assert all(a.source == RoleSource.INFERRED and a.reasons and 0 < a.confidence < 1 for a in plate.assignments)


def test_role_guards(analyzed):
    # a blind hole is never a clearance hole; a hole in a 2 mm wall cannot hold a dowel pin
    cyl = roles_of(analyzed, "cylindrical_part")
    blind = next(f for f in analyzed["cylindrical_part"][0].features if getattr(f, "through", True) is False)
    assert all(not (a.target.ref == blind.id and a.role == FeatureRole.CLEARANCE_HOLES) for a in cyl.assignments)
    assert all(a.role != FeatureRole.DOWEL_HOLE for a in roles_of(analyzed, "enclosure").assignments)


def test_user_override_replaces_the_guess_and_is_validated(analyzed):
    ir, _ = analyzed["flange"]
    bore = next(a for a in roles_of(analyzed, "flange").assignments if a.role == FeatureRole.CENTRAL_BORE)
    r = infer_roles(ir, R, [RoleOverride(target=bore.target, role=FeatureRole.NONE)])
    mine = [a for a in r.assignments if a.target == bore.target]
    assert len(mine) == 1 and mine[0].source == RoleSource.USER and mine[0].role == FeatureRole.NONE
    bad = infer_roles(ir, R, [RoleOverride(target=bore.target, role=FeatureRole.MOUNTING_FACE)])
    assert bad.errors and "planar face" in bad.errors[0]
    _, p = plan(analyzed, "flange", feature_roles=[{"target": {"feature_id": "NOPE"}, "role": "DOWEL_HOLE"}])
    assert any("does not exist" in e for e in p.errors)


def test_minimum_views_and_isometric_only_when_triggered(analyzed):
    _, shaft = plan(analyzed, "shaft")
    assert shaft.plan.primary_view.orientation == ViewOrientation.FRONT and shaft.plan.projected_views == []
    _, flange = plan(analyzed, "flange")
    assert flange.plan.projected_views == [ViewOrientation.TOP]
    for name in ("shaft", "flange", "bracket", "mounting_plate"):
        assert plan(analyzed, name)[1].plan.primary_view.orientation not in PICTORIAL  # simple parts (RULES 1.2)
    _, cast = plan(analyzed, "bracket", general_notes={"process": "CASTING"})
    assert cast.plan.primary_view.orientation in PICTORIAL and not cast.plan.primary_view.dimensioned
    _, manual = plan(analyzed, "bracket", view_selection="MANUAL")
    assert manual.plan.primary_view.orientation == ViewOrientation.ISOMETRIC and len(manual.plan.projected_views) == 3


def test_flat_part_single_view_with_thickness_note(analyzed):
    _, p = plan(analyzed, "plate_with_holes", default_gdt=False)
    assert p.plan.projected_views == [] and p.plan.rule_notes == ["THICKNESS 10.00"]
    # a chunky block is not "flat": its third dimension is never turned into a note
    _, block = plan(analyzed, "chamfered_block", default_gdt=False)
    assert block.plan.rule_notes == []


def test_role_treatments(analyzed):
    _, flange = plan(analyzed, "flange")
    m = flange.plan.manufacturing
    fits = {t.fit: t for t in m.tolerances if t.kind == ToleranceKind.FIT}
    assert fits["H8"].upper == pytest.approx(0.033)  # EX 6: central bore H8
    assert [d.letter for d in m.datums] == ["A", "B"]  # A seating face, B central bore (EX 6: no C)
    pos = next(f for f in m.frames if f.characteristic.value == "POSITION")
    assert pos.material_condition.value == "MMC" and [d.letter for d in pos.datums] == ["A", "B"]
    _, shaft = plan(analyzed, "shaft")
    m = shaft.plan.manufacturing
    assert sorted(t.fit for t in m.tolerances) == ["h6", "h6"]
    assert sorted(f.tolerance for f in m.frames if f.characteristic.value == "CYLINDRICITY") == [0.005, 0.005]
    assert sorted(x.ra_um for x in m.surface_finish_marks) == [0.4, 0.4, 1.6, 1.6]
    eng = shaft.plan.engineering_information
    assert eng.surface_finish.value == "Ra 3.2" and eng.surface_finish.source.value == "DEFAULT"


def test_datum_c_is_never_left_unreferenced(analyzed):
    for name in ("pocketed_block", "plate_with_holes", "mounting_plate", "bracket"):
        m = plan(analyzed, name)[1].plan.manufacturing
        used = {r.letter for f in m.frames for r in f.datums}
        assert {d.letter for d in m.datums} - {"A"} <= used, name


def test_compliance_gate(analyzed):
    ir, p = plan(analyzed, "flange")
    c = build_compliance(p.plan, ir, p.candidates, hard_blockers=R.gate.hard_blockers, stamp_text=R.gate.stamp_text)
    assert not c.releasable and c.stamp == R.gate.stamp_text
    assert {i.number for i in c.blocking} == {1, 11}
    assert c.assumed_roles and all(a.source == RoleSource.INFERRED for a in c.assumed_roles)
    ir, p = plan(analyzed, "flange", title_block={"part_number": "FL-1", "revision": "A"},
                 engineering_information={"material": {"status": "SPECIFIED", "value": "S355", "source": "USER"}})
    c = build_compliance(p.plan, ir, p.candidates, hard_blockers=R.gate.hard_blockers)
    assert c.releasable and c.stamp is None
    # without the rule-set defaults the general tolerance / finish notes / functional tolerances are missing
    ir, p = plan(analyzed, "flange", default_gdt=False)
    c = build_compliance(p.plan, ir, p.candidates, hard_blockers=R.gate.hard_blockers)
    assert {2, 3, 8} <= {i.number for i in c.blocking}
