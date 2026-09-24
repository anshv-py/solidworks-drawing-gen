"""User-selectable scales: sheet scale, isometric scale and the series AUTO chooses from."""

import pytest
from pydantic import ValidationError

from drawing_compiler import LayoutError, compile_drawing
from drawing_executor.pipeline import generate
from drawing_planner import plan_baseline
from drawing_schema import ISO_5455_SCALES, Sheet
from drawing_schema.settings import DrawingSettings


def compiled(analyzed, name, **sheet):
    ir, _ = analyzed[name]
    r = plan_baseline(ir, DrawingSettings.model_validate({"sheet": sheet}))
    return compile_drawing(r.plan, r.candidates, ir)


def views(cd):
    iso = next(v for v in cd.views if v.pictorial)
    return iso, [v for v in cd.views if not v.pictorial]


def test_auto_uses_intermediate_scales_by_default(analyzed):
    assert compiled(analyzed, "flange").scale == "1:1.5"


def test_iso_series_keeps_auto_to_iso_5455(analyzed):
    cd = compiled(analyzed, "flange", scale_system="ISO_5455")
    assert cd.scale == "1:2" and all(v.scale in ISO_5455_SCALES for v in cd.views)


def test_chosen_sheet_scale_is_used_exactly(analyzed):
    cd = compiled(analyzed, "flange", scale="1:5")
    iso, ortho = views(cd)
    assert cd.scale == "1:5" and all(v.scale == "1:5" for v in ortho)
    assert iso.outline.w > 0


def test_chosen_isometric_scale_is_used_and_labelled(analyzed):
    cd = compiled(analyzed, "flange", scale="1:5", pictorial_scale="1:2")
    iso, _ = views(cd)
    assert iso.scale == "1:2" and iso.label == "SCALE 1:2"


def test_scale_that_does_not_fit_fails_with_the_largest_that_does(analyzed):
    ir, _ = analyzed["flange"]
    r = plan_baseline(ir, DrawingSettings.model_validate({"sheet": {"scale": "2:1"}}))
    with pytest.raises(LayoutError, match=r"chosen scale 2:1 - the largest scale that fits is 1:1\.5"):
        compile_drawing(r.plan, r.candidates, ir)


def test_unsupported_scale_is_rejected():
    with pytest.raises(ValidationError):
        Sheet(scale="1:7")
    assert Sheet(scale="1:3", scale_system="ISO_5455").scale == "1:3"  # a chosen scale may be any supported one


def test_pipeline_never_changes_a_chosen_scale(geometry_files, models_dir, tmp_path):
    settings = DrawingSettings.model_validate({"sheet": {"scale": "1:2", "pictorial_scale": "1:1.5"}})
    res = generate(geometry_files["flange"], models_dir / "flange.step", settings, tmp_path)
    assert res.passed and res.scale == "1:2"


@pytest.mark.parametrize("name", ["mounting_plate", "flange", "shaft", "bracket", "pocketed_block",
                                  "plate_with_holes"])
@pytest.mark.parametrize("sheet", [{}, {"scale": "1:5"}, {"scale": "1:5", "pictorial_scale": "1:2"}])
def test_isometric_is_in_the_top_right_corner_at_any_scale(analyzed, name, sheet):
    cd = compiled(analyzed, name, **sheet)
    iso, ortho = views(cd)
    top_right = max(v.outline.x1 for v in cd.views), max(v.outline.y1 for v in cd.views)
    assert iso.outline.x1 == pytest.approx(top_right[0]) and iso.outline.y1 >= top_right[1] - 1e-6
    assert all(iso.outline.x0 > v.outline.x1 or iso.outline.y0 > v.outline.y1 for v in ortho)


def test_chosen_scale_keeps_the_default_gdt(geometry_files, models_dir, tmp_path):
    """At a chosen scale the default GD&T is never dropped silently: it fits, or the layout error
    names the largest scale that does."""
    from drawing_executor.pipeline import DrawingFailed

    settings = DrawingSettings.model_validate({"sheet": {"scale": "1:1"}})
    with pytest.raises(DrawingFailed, match="largest scale that fits"):
        generate(geometry_files["enclosure"], models_dir / "enclosure.step", settings, tmp_path)
    settings = DrawingSettings.model_validate({"sheet": {"scale": "1:2"}})
    res = generate(geometry_files["plate_with_holes"], models_dir / "plate_with_holes.step", settings, tmp_path)
    plan = __import__("json").loads((tmp_path / "plan.json").read_text())
    assert res.passed and plan["manufacturing"]["frames"]
