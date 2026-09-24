import math

import pytest

from geometry_service.analyze import analyze_file
from geometry_service.step_analysis import CadImportError, read_step
from shared_types import Representation, SourceFormat


def test_every_fixture_imports_as_single_valid_solid(analyzed):
    for name, (ir, _) in analyzed.items():
        assert ir.representation == Representation.EXACT_BREP, name
        assert ir.topology.solids == 1, name
        assert ir.bodies[0].is_valid, name
        assert ir.units.length == "mm"
        assert not [d for d in ir.diagnostics if d.severity == "ERROR"], name


@pytest.mark.parametrize(
    "name",
    ["plate_with_holes", "mounting_plate", "pocketed_block", "bracket", "shaft", "flange",
     "cylindrical_part", "enclosure", "chamfered_block"],
)
def test_bounding_box_matches_construction(analyzed, manifest, name):
    ir, _ = analyzed[name]
    expected = manifest["models"][name]["expected"]["bbox_size"]
    assert ir.bounding_box.size == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("name", ["plate_with_holes", "pocketed_block", "flange", "enclosure"])
def test_volume_matches_construction(analyzed, manifest, name):
    ir, _ = analyzed[name]
    assert ir.mass_properties.volume == pytest.approx(manifest["models"][name]["expected"]["volume"], rel=1e-6)


def test_centroid_and_principal_axes_of_symmetric_part(analyzed):
    ir, _ = analyzed["plate_with_holes"]
    assert ir.mass_properties.centroid == pytest.approx((60.0, 40.0, 5.0), abs=1e-6)
    dirs = [a.direction for a in ir.principal_axes]
    # principal axes of a plate symmetric about x=60 and y=40 are the global axes
    for d in dirs:
        assert max(abs(c) for c in d) == pytest.approx(1.0, abs=1e-6)
    moments = [a.moment for a in ir.principal_axes]
    assert moments == sorted(moments)


def test_symmetry_candidates_found_for_plate(analyzed):
    ir, _ = analyzed["plate_with_holes"]
    normals = {tuple(round(c, 6) for c in s.plane_normal) for s in ir.symmetry_candidates if s.score == 1.0}
    assert (1.0, 0.0, 0.0) in normals and (0.0, 1.0, 0.0) in normals and (0.0, 0.0, 1.0) in normals


@pytest.mark.parametrize("variant,unit", [("plate_with_holes_metres.step", "metre"), ("plate_with_holes_inches.step", "INCH")])
def test_file_units_are_converted_to_mm(models_dir, manifest, variant, unit):
    ir, _ = analyze_file(models_dir / variant, SourceFormat.STEP, with_preview=False)
    assert ir.source.file_length_units == [unit]
    assert ir.bounding_box.size == pytest.approx(manifest["unit_variants"][variant]["expected"]["bbox_size"], abs=1e-6)
    diam = sorted({round(h.diameter, 6) for h in ir.features if h.type == "HOLE"})
    assert diam == [8.0, 20.0]


def test_garbage_step_is_rejected(tmp_path):
    bad = tmp_path / "bad.step"
    bad.write_text("ISO-10303-21;\nthis is not a step file\n")
    with pytest.raises(CadImportError):
        read_step(bad)


def test_source_metadata(analyzed, models_dir):
    ir, _ = analyzed["flange"]
    assert ir.source.format == SourceFormat.STEP
    assert len(ir.source.sha256) == 64
    assert ir.source.kernel == "OCCT" and ir.source.kernel_version.startswith("OCP ")
    assert ir.source.size_bytes == (models_dir / "flange.step").stat().st_size
    assert not math.isnan(ir.analysis.duration_s)
