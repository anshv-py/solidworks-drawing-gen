import pytest

from drawing_compiler import CompileOptions, LayoutError, compile_drawing
from drawing_planner import plan_baseline
from drawing_qa import Rendered, validate
from drawing_schema import ISO_5455_SCALES, ProjectionMethod
from drawing_schema.settings import DrawingSettings


def compiled(analyzed, name, **settings):
    ir, _ = analyzed[name]
    r = plan_baseline(ir, DrawingSettings.model_validate(settings))
    return ir, r, compile_drawing(r.plan, r.candidates, ir)


def centre(cd, orientation):
    return next(v for v in cd.views if v.orientation == orientation).sheet_center


@pytest.mark.parametrize("method", ["FIRST_ANGLE", "THIRD_ANGLE"])
def test_projection_placement(analyzed, method):
    _, _, cd = compiled(analyzed, "bracket", projection_method=method)
    fx, fy = centre(cd, "FRONT")
    tx, ty = centre(cd, "TOP")
    rx, ry = centre(cd, "RIGHT")
    assert tx == pytest.approx(fx) and ry == pytest.approx(fy)
    if method == ProjectionMethod.FIRST_ANGLE:
        assert ty < fy and rx < fx  # ISO first angle: top view below, right view on the left
    else:
        assert ty > fy and rx > fx


def test_scale_is_iso_and_largest_that_fits(analyzed):
    ir, r, cd = compiled(analyzed, "mounting_plate")
    assert cd.scale in ISO_5455_SCALES
    bigger = ISO_5455_SCALES[ISO_5455_SCALES.index(cd.scale) - 1]
    from drawing_compiler.compiler import Compiler, scale_factor

    assert Compiler(r.plan, r.candidates, ir)._layout(scale_factor(bigger)) is None


def test_every_selected_dimension_is_placed_once(analyzed):
    _, r, cd = compiled(analyzed, "plate_with_holes")
    assert sorted(d.id for d in cd.dimensions) == sorted(s.candidate_id for s in r.plan.dimension_selections)


def test_sheet_distances_match_values(analyzed):
    _, r, cd = compiled(analyzed, "pocketed_block")
    scale = {v.id: v.scale_factor for v in cd.views}
    for d in cd.dimensions:
        if d.kind == "LINEAR":
            span = abs(d.p2[0] - d.p1[0]) if d.horizontal else abs(d.p2[1] - d.p1[1])
            assert span / scale[d.view_id] == pytest.approx(d.value, abs=1e-6)


def test_title_block_never_invents_engineering_data(analyzed):
    _, _, cd = compiled(analyzed, "flange")
    f = {x.label: x.value for x in cd.title_fields}
    assert f["MATERIAL"] == f["GENERAL TOL."] == f["SURFACE FINISH"] == "UNSPECIFIED"
    assert f["TYPE"] == "GEOMETRY DRAWING" and f["PROJECTION"] == "FIRST ANGLE"


def test_tiny_sheet_forces_smaller_scale_or_fails(analyzed):
    ir, r, _ = compiled(analyzed, "enclosure")
    plan = type(r.plan).model_validate({**r.plan.model_dump(), "sheet": {"size": "A4", "orientation": "LANDSCAPE"}})
    cd = compile_drawing(plan, r.candidates, ir)
    assert ISO_5455_SCALES.index(cd.scale) >= ISO_5455_SCALES.index("1:2")
    with pytest.raises(LayoutError):
        compile_drawing(plan, r.candidates, ir, CompileOptions(max_scale="1:1000", tier_gap=400))


def _fake_render(cd):
    """Pretend-render: each view's geometry = its analytic outline rectangle."""
    lines = {}
    for v in cd.views:
        o = v.outline
        lines[v.id] = {"visible": [[(o.x0, o.y0), (o.x1, o.y0), (o.x1, o.y1), (o.x0, o.y1), (o.x0, o.y0)]],
                       "hidden": []}
    return Rendered(lines=lines)


def test_qa_catches_view_that_disagrees_with_geometry(analyzed):
    ir, r, cd = compiled(analyzed, "plate_with_holes")
    rendered = _fake_render(cd)
    front = next(v for v in cd.views if v.orientation == "FRONT")
    pl = rendered.lines[front.id]["visible"][0]
    rendered.lines[front.id]["visible"][0] = [(x * 1.1, y) for x, y in pl]  # drawn 10 % too wide
    ids = {i.check_id for i in validate(r.plan, r.candidates, ir, cd, rendered).issues if i.severity == "CRITICAL"}
    assert "QA-VIEW-002" in ids


def test_qa_catches_tampered_label(analyzed):
    ir, r, cd = compiled(analyzed, "plate_with_holes")
    dims = [d.model_copy(update={"text": "121"}) if d.id == "DIM-OVERALL-X" else d for d in cd.dimensions]
    bad = cd.model_copy(update={"dimensions": dims})
    rep = validate(r.plan, r.candidates, ir, bad, _fake_render(bad))
    assert not rep.passed and any(i.check_id == "QA-DIM-001" for i in rep.issues)


def test_qa_catches_invented_material(analyzed):
    ir, r, cd = compiled(analyzed, "plate_with_holes")
    fields = [f.model_copy(update={"value": "S235JR"}) if f.label == "MATERIAL" else f for f in cd.title_fields]
    bad = cd.model_copy(update={"title_fields": fields})
    rep = validate(r.plan, r.candidates, ir, bad, _fake_render(bad))
    assert any(i.check_id == "QA-TB-001" and i.severity == "CRITICAL" for i in rep.issues)


def test_qa_catches_overlapping_views(analyzed):
    ir, r, cd = compiled(analyzed, "plate_with_holes")
    views = list(cd.views)
    front = next(v for v in views if v.orientation == "FRONT")
    top = next(v for v in views if v.orientation == "TOP")
    moved = top.model_copy(update={"sheet_center": front.sheet_center, "outline": front.outline})
    bad = cd.model_copy(update={"views": [moved if v.id == top.id else v for v in views]})
    rep = validate(r.plan, r.candidates, ir, bad, _fake_render(bad))
    assert any(i.check_id == "QA-VIEW-001" and i.repair == "REDUCE_SCALE" for i in rep.issues)
