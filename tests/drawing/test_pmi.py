"""User-supplied manufacturing annotations (GD&T, datums, tolerances, finish): validated against
GeometryIR, placed without collisions, drawn, and checked by QA. Nothing is generated."""

import ezdxf
import pytest
from pydantic import ValidationError

from drawing_compiler import compile_drawing
from drawing_executor.pipeline import DrawingFailed, generate
from drawing_planner import plan_baseline
from drawing_qa import Rendered, validate
from drawing_schema.pmi import FeatureControlFrame, ManufacturingAnnotations
from drawing_schema.settings import DrawingSettings
from geometry_schema import FeatureType, SurfaceType


def flange_ids(ir):
    planes = {round(f.centroid[2], 3): f.id for f in ir.faces if f.surface_type == SurfaceType.PLANE}
    feats = {f.type: f for f in ir.features}
    bore = next(f for f in ir.features if f.type == FeatureType.HOLE and f.diameter == 20.0)
    boss = next(f for f in ir.features if f.type == FeatureType.BOSS and f.diameter == 100.0)
    return planes[0.0], planes[40.0], bore.id, boss.id, feats[FeatureType.PATTERN].id


def pmi_settings(ir, **extra) -> DrawingSettings:
    bottom, top, bore, boss, pattern = flange_ids(ir)
    return DrawingSettings.model_validate({
        "drawing_kind": "MANUFACTURING",
        "title_block": {"title": "Flange", "drawing_number": "FL-001", "revision": "A"},
        "engineering_information": {
            "material": {"status": "SPECIFIED", "value": "AISI 304", "source": "USER"},
            "general_tolerance": {"status": "SPECIFIED", "value": "ISO 2768-mK", "source": "USER"},
        },
        "manufacturing": {
            "datums": [{"letter": "A", "target": {"face_id": bottom}},
                       {"letter": "B", "target": {"feature_id": bore}},
                       {"letter": "C", "target": {"feature_id": boss}}],
            "frames": [
                {"characteristic": "FLATNESS", "tolerance": 0.05, "target": {"face_id": bottom}},
                {"characteristic": "PARALLELISM", "tolerance": 0.1, "datums": [{"letter": "A"}],
                 "target": {"face_id": top}},
                {"characteristic": "POSITION", "tolerance": 0.1, "diameter_zone": True, "material_condition": "MMC",
                 "datums": [{"letter": "A"}, {"letter": "B"}, {"letter": "C"}], "target": {"feature_id": pattern}},
            ],
            "tolerances": [{"candidate_id": "DIM-OVERALL-Z", "kind": "SYMMETRIC", "upper": 0.1}],
            "inspection_dimensions": ["DIM-OVERALL-Z"],
            "surface_finish_marks": [{"target": {"face_id": top}, "ra_um": 0.8}],
            "notes": ["Break all edges"],
            "revisions": [{"revision": "A", "description": "Initial release"}],
            **extra,
        },
    })


# ---------------------------------------------------------------- schema grammar

@pytest.mark.parametrize("frame,msg", [
    ({"characteristic": "FLATNESS", "tolerance": 0.05, "datums": [{"letter": "A"}]}, "form tolerance"),
    ({"characteristic": "PARALLELISM", "tolerance": 0.05}, "requires at least one datum"),
    ({"characteristic": "FLATNESS", "tolerance": 0.05, "diameter_zone": True}, "diameter"),
    ({"characteristic": "CIRCULAR_RUNOUT", "tolerance": 0.05, "material_condition": "MMC",
      "datums": [{"letter": "A"}]}, "MMC"),
])
def test_gdt_grammar_is_enforced(frame, msg):
    with pytest.raises(ValidationError, match=msg):
        FeatureControlFrame.model_validate({**frame, "target": {"face_id": "F"}})


def test_frames_may_only_reference_defined_datums():
    with pytest.raises(ValidationError, match="not defined"):
        ManufacturingAnnotations.model_validate({"frames": [
            {"characteristic": "PERPENDICULARITY", "tolerance": 0.1, "datums": [{"letter": "A"}],
             "target": {"face_id": "F"}}]})


def test_unknown_or_unsuitable_targets_are_rejected(analyzed):
    ir, _ = analyzed["flange"]
    s = pmi_settings(ir)
    bad = s.model_copy(update={"manufacturing": s.manufacturing.model_copy(update={
        "datums": [*s.manufacturing.datums[1:], s.manufacturing.datums[0].model_copy(
            update={"target": s.manufacturing.datums[0].target.model_copy(update={"face_id": "FACE-nope"})})]})})
    assert plan_baseline(ir, bad).errors


# ---------------------------------------------------------------- compile + QA

def test_every_annotation_is_placed_once(analyzed):
    ir, _ = analyzed["flange"]
    r = plan_baseline(ir, pmi_settings(ir))
    assert r.errors == []
    cd = compile_drawing(r.plan, r.candidates, ir)
    assert not [n for n in cd.notes if n.startswith(("UNPLACED", "CROWDED"))], cd.notes
    datums = sorted([d.datum for d in cd.dimensions if d.datum] + [p.datum for p in cd.pmi if p.datum])
    assert datums == ["A", "B", "C"]
    frames = [f for d in cd.dimensions for f in d.frames] + [f for p in cd.pmi for f in p.frames]
    assert sorted(f.cells[0].symbol for f in frames) == ["FLATNESS", "PARALLELISM", "POSITION"]
    pos = next(f for f in frames if f.cells[0].symbol == "POSITION")
    assert pos.cells[1].diameter and pos.cells[1].modifier == "MMC" and pos.cells[1].text == "0.10"
    assert [c.text for c in pos.cells[2:]] == ["A", "B", "C"]
    z = next(d for d in cd.dimensions if d.id == "DIM-OVERALL-Z")
    assert z.tolerance.upper == "±0.10" and z.inspection
    assert cd.sheet_notes[0].startswith("1) DIMENSIONING AND TOLERANCING PER ISO GPS")
    assert any(line.startswith("16) Break all edges") for line in cd.sheet_notes)  # user notes follow note 15
    assert cd.revision_rows == [["A", "Initial release", "", ""]]
    # nothing overlaps the notes block / revision table / title block
    for p in cd.pmi:
        for blk in (cd.title_block, cd.notes_rect, cd.revision_rect):
            assert not p.bbox.intersects(blk)


def test_qa_detects_a_dropped_datum(analyzed):
    ir, _ = analyzed["flange"]
    r = plan_baseline(ir, pmi_settings(ir))
    cd = compile_drawing(r.plan, r.candidates, ir)
    stripped = cd.model_copy(update={"pmi": [p.model_copy(update={"datum": None, "datum_box": None}) for p in cd.pmi]})
    rep = validate(r.plan, r.candidates, ir, stripped, Rendered(lines={v.id: {"visible": [], "hidden": []}
                                                                      for v in cd.views}))
    assert any(i.check_id == "QA-PMI-002" and "datum A" in i.message for i in rep.issues)


# ---------------------------------------------------------------- executor

def test_drawing_with_gdt_passes_qa_and_draws_symbols(analyzed, geometry_files, models_dir, tmp_path):
    ir, _ = analyzed["flange"]
    res = generate(geometry_files["flange"], models_dir / "flange.step", pmi_settings(ir), tmp_path)
    assert res.passed
    msp = ezdxf.readfile(tmp_path / "drawing.dxf").modelspace()
    texts = [t.dxf.text for t in msp.query("TEXT")]
    for expected in ("A", "B", "C", "0.10", "0.05", "±0.10", "Ra 0.8", "Note:", "REVISIONS", "AISI 304",
                     "FL-001", "DO NOT SCALE DRAWING", "UNLESS OTHERWISE SPECIFIED:"):
        assert expected in texts, expected
    assert len(msp.query("*[layer=='GDT']")) > 20  # frames, symbols, datum triangles
    assert len(msp.query("SOLID[layer=='SHADE']")) > 100  # shaded isometric
    # provenance lives inside the title block, not in the drawing area's bottom-left corner
    tb_x0 = 420 - 10 - 180
    for t in msp.query("TEXT"):
        if "NOT PRODUCED BY SOLIDWORKS" in t.dxf.text:
            assert t.dxf.insert[0] >= tb_x0


def test_invalid_annotations_fail_the_job(analyzed, geometry_files, models_dir, tmp_path):
    ir, _ = analyzed["flange"]
    s = pmi_settings(ir, tolerances=[{"candidate_id": "DIM-DOES-NOT-EXIST", "kind": "SYMMETRIC", "upper": 0.1}])
    with pytest.raises(DrawingFailed) as e:
        generate(geometry_files["flange"], models_dir / "flange.step", s, tmp_path)
    assert e.value.code == "PMI_INVALID"
