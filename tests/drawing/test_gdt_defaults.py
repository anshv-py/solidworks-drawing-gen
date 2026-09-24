"""Default datums and GD&T (drawing_planner.gdt_defaults): applied directly, derived from ISO 2768-mK,
consistent with the datum-scheme rules, and never the reason a drawing cannot be made."""

import json

import pytest

from drawing_compiler import compile_drawing
from drawing_executor.pipeline import generate
from drawing_planner import plan_baseline
from drawing_planner.datum_rules import check_datum_scheme
from drawing_planner.gdt_defaults import flatness_k, linear_m, perpendicularity_k, position_zone, tighter_than
from drawing_schema.settings import DrawingSettings
from geometry_schema import FeatureType, SurfaceType


def planned(analyzed, name, **settings):
    ir, _ = analyzed[name]
    return ir, plan_baseline(ir, DrawingSettings.model_validate(settings), filename=f"{name}.step")


def test_iso_2768_tables():
    assert [linear_m(x) for x in (5, 30, 31, 120, 150, 500)] == [0.1, 0.2, 0.3, 0.3, 0.5, 0.8]
    assert [flatness_k(x) for x in (10, 25, 100, 150)] == [0.05, 0.1, 0.2, 0.4]
    assert [perpendicularity_k(x) for x in (50, 100, 200)] == [0.4, 0.4, 0.6]
    # Ø zone circumscribing the ±t square, rounded down to 0.05: ±0.3 -> Ø0.849 -> Ø0.80
    assert position_zone(115) == pytest.approx(0.8) and position_zone(20) == pytest.approx(0.55)
    assert tighter_than(0.4) == 0.3 and tighter_than(0.2) == 0.15


def test_prismatic_part_gets_the_bounding_box_datum_corner(analyzed):
    ir, r = planned(analyzed, "plate_with_holes")
    m = r.plan.manufacturing
    faces = {f.id: f for f in ir.faces}
    bb = ir.bounding_box
    assert [d.letter for d in m.datums] == ["A", "B", "C"]
    for d in m.datums:  # every datum is a planar face on a bounding-box minimum side
        f = faces[d.target.face_id]
        assert f.surface_type == SurfaceType.PLANE
        k = max(range(3), key=lambda i: abs(f.surface.normal[i]))
        assert f.centroid[k] == pytest.approx(bb.min[k], abs=1e-6)
    a = faces[m.datums[0].target.face_id]
    assert a.area == max(faces[d.target.face_id].area for d in m.datums)  # primary = largest seat
    chars = sorted(f.characteristic.value for f in m.frames)
    assert chars == ["FLATNESS", "PERPENDICULARITY", "PERPENDICULARITY", "POSITION", "POSITION"]
    for f in m.frames:
        if f.characteristic.value == "POSITION":
            assert f.diameter_zone and [x.letter for x in f.datums] == ["A", "B", "C"]
    # hole locations are theoretically exact, the overall sizes are not
    assert m.basic_dimensions and all("OVERALL" not in c for c in m.basic_dimensions)
    assert r.errors == []


def test_flange_is_referenced_to_seat_face_and_axis(analyzed):
    ir, r = planned(analyzed, "flange")
    m = r.plan.manufacturing
    feats = {f.id: f for f in ir.features}
    a, b = m.datums
    assert a.letter == "A" and a.target.face_id is not None
    assert b.letter == "B" and feats[b.target.feature_id].type == FeatureType.BOSS
    positions = [f for f in m.frames if f.characteristic.value == "POSITION"]
    assert positions and all([x.letter for x in f.datums] == ["A", "B"] for f in positions)
    assert any(c.startswith("DIM-PCD") for c in m.basic_dimensions)


def test_shaft_is_referenced_to_its_longest_journal(analyzed):
    ir, r = planned(analyzed, "shaft")
    m = r.plan.manufacturing
    feats = {f.id: f for f in ir.features}
    (a,) = m.datums
    assert feats[a.target.feature_id].type == FeatureType.BOSS
    assert {f.characteristic.value for f in m.frames} == {"STRAIGHTNESS", "CIRCULAR_RUNOUT"}


@pytest.mark.parametrize("name", ["plate_with_holes", "mounting_plate", "flange", "shaft", "bracket",
                                  "pocketed_block", "enclosure"])
def test_default_scheme_satisfies_the_datum_rules(analyzed, name):
    ir, r = planned(analyzed, name)
    assert r.errors == []
    assert check_datum_scheme(ir, r.plan.manufacturing) == []  # R3 (form tighter), R8, R9, measurable


def test_general_tolerance_is_labelled_as_a_default(analyzed):
    _, r = planned(analyzed, "flange")
    g = r.plan.engineering_information.general_tolerance
    assert g.status == "SPECIFIED" and g.value == "ISO 2768-mK" and g.source == "DEFAULT"
    assert r.plan.engineering_information.material.status == "UNSPECIFIED"  # still never invented
    user = {"status": "SPECIFIED", "value": "ISO 2768-fH", "source": "USER"}
    _, r = planned(analyzed, "flange", engineering_information={"general_tolerance": user})
    assert r.plan.engineering_information.general_tolerance.value == "ISO 2768-fH"


def test_user_scheme_replaces_the_defaults(analyzed):
    ir, _ = analyzed["plate_with_holes"]
    bottom = min((f for f in ir.faces if f.surface_type == SurfaceType.PLANE), key=lambda f: f.centroid[2])
    _, r = planned(analyzed, "plate_with_holes", manufacturing={
        "datums": [{"letter": "A", "target": {"face_id": bottom.id}}],
        "frames": [{"characteristic": "FLATNESS", "tolerance": 0.05, "target": {"face_id": bottom.id}}]})
    m = r.plan.manufacturing
    assert [d.letter for d in m.datums] == ["A"] and len(m.frames) == 1 and m.basic_dimensions == []


def test_defaults_can_be_turned_off(analyzed):
    _, r = planned(analyzed, "plate_with_holes", default_gdt=False)
    assert r.plan.manufacturing.is_empty
    assert r.plan.engineering_information.general_tolerance.status == "UNSPECIFIED"


def test_isometric_is_top_right_and_larger_than_the_views(analyzed):
    ir, r = planned(analyzed, "flange")
    cd = compile_drawing(r.plan, r.candidates, ir)
    iso = next(v for v in cd.views if v.pictorial)
    ortho = [v for v in cd.views if not v.pictorial]
    assert iso.outline.x0 > max(v.outline.x1 for v in ortho)  # right of every orthographic view
    assert iso.outline.y1 > cd.title_block.y1  # above the title block / notes
    size = lambda v: max(v.outline.w, v.outline.h)  # noqa: E731
    assert size(iso) > max(size(v) for v in ortho)


def test_default_notes_are_concise_and_complete(analyzed):
    ir, r = planned(analyzed, "plate_with_holes")
    cd = compile_drawing(r.plan, r.candidates, ir)
    text = " ".join(cd.sheet_notes)
    assert "ISO 2768-mK" in text and "DATUM REFERENCE FRAME: A = PLANAR FACE" in text and "TED" in text
    assert "[" not in text  # no placeholders
    assert len(cd.sheet_notes) <= 10


@pytest.mark.parametrize("name", ["mounting_plate", "flange", "shaft"])
def test_default_gdt_drawings_pass_qa(geometry_files, models_dir, tmp_path, name):
    res = generate(geometry_files[name], models_dir / f"{name}.step", DrawingSettings(), tmp_path)
    assert res.passed
    qa = json.loads((tmp_path / "qa_report.json").read_text())
    assert not [i for i in qa["issues"] if i["severity"] in ("CRITICAL", "MAJOR")], qa["issues"]
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert plan["manufacturing"]["datums"] and plan["manufacturing"]["frames"]


def test_defaults_that_do_not_fit_are_dropped_not_fatal(geometry_files, models_dir, tmp_path):
    settings = DrawingSettings.model_validate({"sheet": {"size": "A4", "orientation": "LANDSCAPE"}})
    res = generate(geometry_files["enclosure"], models_dir / "enclosure.step", settings, tmp_path)
    assert res.artifacts
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert plan["manufacturing"]["datums"] == [] and plan["manufacturing"]["frames"] == []
    assert any("default datums / GD&T omitted" in u["message"] for u in plan["uncertainties"])
