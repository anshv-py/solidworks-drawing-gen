"""Default drawing notes (with placeholders, never invented values) and the datum-scheme rules."""

import pytest

from drawing_compiler import compile_drawing
from drawing_compiler.notes import build_notes, placeholders
from drawing_planner import plan_baseline
from drawing_planner.datum_rules import check_datum_scheme, suggest_datums
from drawing_qa import Rendered, validate
from drawing_schema.pmi import ManufacturingAnnotations, ManufacturingProcess
from drawing_schema.settings import DrawingSettings
from geometry_schema import FeatureType, SurfaceType


def plan(analyzed, name, **settings):
    ir, _ = analyzed[name]
    return ir, plan_baseline(ir, DrawingSettings.model_validate(settings), filename=f"{name}.step")


def face(ir, axis, value):
    k = "XYZ".index(axis)
    return next(f.id for f in ir.faces if f.surface_type == SurfaceType.PLANE
                and abs(abs(f.surface.normal[k]) - 1) < 1e-9 and abs(f.centroid[k] - value) < 1e-6)


# ---------------------------------------------------------------- notes

def test_default_notes_are_on_in_the_required_order_with_placeholders(analyzed):
    ir, r = plan(analyzed, "flange")
    notes, bullets, summary = build_notes(r.plan, ir)
    assert len(notes) == 15 and len(bullets) == 4
    starts = ["DIMENSIONING AND TOLERANCING PER ISO GPS", "GENERAL TOLERANCES", "GENERAL GEOMETRIC TOLERANCE",
              "DATUM REFERENCE FRAME", "INDEPENDENCY PRINCIPLE", "DATUM FEATURE FORM", "SURFACE FINISH",
              "[BURR", "MATERIAL: [MATERIAL]. NO SUBSTITUTION WITHOUT WRITTEN APPROVAL", "HEAT TREATMENT",
              "THREADS", "PROCESS", "THIS DRAWING GOVERNS 3D MODEL flange.step", "INSPECTION", "MARKING"]
    for n, s in zip(notes, starts):
        assert n.startswith(s), (n, s)
    assert "DO NOT SCALE DRAWING" in notes[0] and "ALL DIMENSIONS IN MM" in notes[0]
    assert summary.startswith("CONTROLLING STANDARD: ISO GPS")
    # nothing supplied -> nothing invented
    assert "[MATERIAL]" in placeholders(notes) and "[GENERAL LINEAR TOLERANCE]" in placeholders(notes)


def test_notes_use_supplied_values_verbatim_and_asme_terms(analyzed):
    ir, _ = analyzed["flange"]
    bottom = face(ir, "Z", 0.0)
    ir, r = plan(analyzed, "flange", drawing_standard="ASME",
                 engineering_information={"material": {"status": "SPECIFIED", "value": "6061-T6", "source": "USER"},
                                          "general_tolerance": {"status": "SPECIFIED", "value": "±0.1",
                                                                "source": "USER"}},
                 general_notes={"general_geometric_tolerance": "PROFILE 0.2 |A|B|C|", "thread_class": "6H/6g",
                                "process": "CNC_MACHINED"},
                 manufacturing={"datums": [{"letter": "A", "target": {"face_id": bottom}}],
                                "frames": [{"characteristic": "FLATNESS", "tolerance": 0.02,
                                            "target": {"face_id": bottom}}]})
    notes, _, summary = build_notes(r.plan, ir)
    assert notes[0].startswith("DIMENSIONING AND TOLERANCING PER ASME Y14.5-2018")
    assert "LINEAR: ±0.1" in notes[1] and "PROFILE 0.2 |A|B|C|" in notes[2]
    assert notes[3] == "DATUM REFERENCE FRAME: A = PLANAR FACE -Z (Z = 0.00)."
    assert "RULE #1" in notes[4] and "RMB" in notes[4] and "MMB" in notes[4]
    assert "A: FLATNESS 0.02" in notes[5]
    assert notes[8].startswith("MATERIAL: 6061-T6.") and "6H/6g" in notes[10] and "CNC MACHINED" in notes[11]
    assert "ASME Y14.5-2018" in summary and "±0.1" in summary


def test_notes_can_be_turned_off(analyzed):
    ir, r = plan(analyzed, "plate_with_holes", general_notes={"enabled": False})
    cd = compile_drawing(r.plan, r.candidates, ir)
    assert cd.sheet_notes == ["1) ALL DIMENSIONS ARE IN MM"]


def test_notes_block_is_legible_and_clear_of_views(analyzed):
    ir, r = plan(analyzed, "mounting_plate")
    cd = compile_drawing(r.plan, r.candidates, ir)
    assert cd.scale == "1:2"  # the two-column band keeps the plate at 1:2
    assert cd.notes_split is not None
    for v in cd.views:
        assert not v.outline.intersects(cd.notes_rect)


def test_qa_reports_unresolved_placeholders(analyzed):
    ir, r = plan(analyzed, "plate_with_holes")
    cd = compile_drawing(r.plan, r.candidates, ir)
    rep = validate(r.plan, r.candidates, ir, cd, Rendered(lines={v.id: {"visible": [], "hidden": []} for v in cd.views}))
    issue = next(i for i in rep.issues if i.check_id == "QA-NOTE-001")
    assert issue.severity == "MAJOR" and "[MATERIAL]" in issue.message


# ---------------------------------------------------------------- datum rules

def scheme(**kw):
    return ManufacturingAnnotations.model_validate(kw)


def test_rule_8_self_reference_and_one_datum_one_job(analyzed):
    ir, _ = analyzed["flange"]
    bottom = face(ir, "Z", 0.0)
    m = scheme(datums=[{"letter": "A", "target": {"face_id": bottom}}, {"letter": "B", "target": {"face_id": bottom}}],
               frames=[{"characteristic": "PARALLELISM", "tolerance": 0.1, "datums": [{"letter": "A"}],
                        "target": {"face_id": bottom}}])
    rules = [(f.rule, f.message) for f in check_datum_scheme(ir, m)]
    assert any(r == "R8" and "self-referencing" in msg for r, msg in rules)
    assert any(r == "R8" and "same feature" in msg for r, msg in rules)
    assert any(r == "R9" and "datum B" in msg for r, msg in rules)  # B is never referenced


def test_rule_3_datum_form_must_exist_and_be_tighter(analyzed):
    ir, _ = analyzed["flange"]
    bottom, top = face(ir, "Z", 0.0), face(ir, "Z", 40.0)
    base = dict(datums=[{"letter": "A", "target": {"face_id": bottom}}],
                frames=[{"characteristic": "PARALLELISM", "tolerance": 0.05, "datums": [{"letter": "A"}],
                         "target": {"face_id": top}}])
    missing = check_datum_scheme(ir, scheme(**base))
    assert any(f.rule == "R3" and f.severity == "MAJOR" and "no flatness" in f.message for f in missing)
    loose = scheme(datums=base["datums"], frames=base["frames"] + [
        {"characteristic": "FLATNESS", "tolerance": 0.05, "target": {"face_id": bottom}}])
    assert any(f.rule == "R3" and "not tighter" in f.message for f in check_datum_scheme(ir, loose))
    good = scheme(datums=base["datums"], frames=base["frames"] + [
        {"characteristic": "FLATNESS", "tolerance": 0.02, "target": {"face_id": bottom}}])
    assert not [f for f in check_datum_scheme(ir, good) if f.rule in ("R3", "R8", "R9")]


def test_rule_7_sheet_metal_edge_datum(analyzed):
    ir, _ = analyzed["plate_with_holes"]
    edge = face(ir, "X", 0.0)  # the 10 mm thick side face
    m = scheme(datums=[{"letter": "A", "target": {"face_id": edge}}])
    findings = check_datum_scheme(ir, m, ManufacturingProcess.SHEET_METAL)
    assert any(f.rule == "R7" for f in findings)
    assert not any(f.rule == "R7" for f in check_datum_scheme(ir, m, ManufacturingProcess.CNC_MACHINED))


def test_unmeasurable_tolerances_are_flagged(analyzed):
    ir, _ = analyzed["flange"]
    bottom = face(ir, "Z", 0.0)
    m = scheme(frames=[{"characteristic": "FLATNESS", "tolerance": 0.002, "target": {"face_id": bottom}}],
               tolerances=[{"candidate_id": "DIM-OVERALL-Z", "kind": "SYMMETRIC", "upper": 0.002}])
    assert sum(f.rule == "MEAS" for f in check_datum_scheme(ir, m)) == 2


@pytest.mark.parametrize("name", ["flange", "plate_with_holes", "bracket", "mounting_plate", "shaft",
                                  "pocketed_block", "enclosure", "chamfered_block", "cylindrical_part"])
def test_suggestion_is_deterministic_and_references_real_geometry(analyzed, name):
    ir, _ = analyzed[name]
    a, cautions = suggest_datums(ir)
    b, _ = suggest_datums(ir)
    assert [(s.letter, s.target) for s in a] == [(s.letter, s.target) for s in b]
    ids = {f.id for f in ir.faces} | {f.id for f in ir.features}
    assert a and all(s.target.ref in ids and s.reasons for s in a)
    assert [s.letter for s in a] == ["A", "B", "C"][: len(a)]
    assert any("rule 1" in c for c in cautions)  # function must be confirmed by the user


def test_suggestion_follows_rules_1_and_2(analyzed):
    ir, _ = analyzed["flange"]
    s, _ = suggest_datums(ir)
    feats = {f.id: f for f in ir.features}
    assert s[0].target.face_id == face(ir, "Z", 0.0)
    b = feats[s[1].target.feature_id]
    assert b.type == FeatureType.BOSS and b.diameter == 45.0  # the pilot, not the Ø100 flange (rule 1)
    ir, _ = analyzed["shaft"]
    s, _ = suggest_datums(ir)
    assert ir.features and next(f for f in ir.features if f.id == s[0].target.feature_id).type == FeatureType.BOSS
