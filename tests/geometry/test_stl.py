import pytest

from geometry_service.analyze import analyze_file
from shared_types import Representation, SourceFormat

ASCII_CUBE = """solid cube
""" + "".join(
    f"  facet normal 0 0 0\n    outer loop\n      vertex {a}\n      vertex {b}\n      vertex {c}\n    endloop\n  endfacet\n"
    for a, b, c in [
        ("0 0 0", "10 10 0", "10 0 0"), ("0 0 0", "0 10 0", "10 10 0"),
        ("0 0 10", "10 0 10", "10 10 10"), ("0 0 10", "10 10 10", "0 10 10"),
        ("0 0 0", "10 0 0", "10 0 10"), ("0 0 0", "10 0 10", "0 0 10"),
        ("0 10 0", "10 10 10", "10 10 0"), ("0 10 0", "0 10 10", "10 10 10"),
        ("0 0 0", "0 0 10", "0 10 10"), ("0 0 0", "0 10 10", "0 10 0"),
        ("10 0 0", "10 10 0", "10 10 10"), ("10 0 0", "10 10 10", "10 0 10"),
    ]
) + "endsolid cube\n"


def test_ascii_stl_cube_exact_for_planar_mesh(tmp_path):
    p = tmp_path / "cube.stl"
    p.write_text(ASCII_CUBE)
    ir, preview = analyze_file(p, SourceFormat.STL)
    assert ir.representation == Representation.TESSELLATED
    assert ir.bounding_box.size == pytest.approx((10, 10, 10))
    assert ir.mass_properties.volume == pytest.approx(1000.0)
    assert ir.mass_properties.surface_area == pytest.approx(600.0)
    assert ir.mass_properties.centroid == pytest.approx((5, 5, 5))
    assert ir.topology.triangles == 12 and ir.topology.vertices == 8
    assert ir.bodies[0].is_closed
    assert len(preview["indices"]) == 36


@pytest.mark.parametrize("name", ["plate_with_holes", "flange", "bracket"])
def test_binary_stl_close_to_exact_step(models_dir, analyzed, name):
    step_ir, _ = analyzed[name]
    ir, _ = analyze_file(models_dir / f"{name}.stl", SourceFormat.STL, with_preview=False)
    assert ir.bounding_box.size == pytest.approx(step_ir.bounding_box.size, abs=0.05)
    assert ir.mass_properties.volume == pytest.approx(step_ir.mass_properties.volume, rel=5e-3)
    codes = {d.code for d in ir.diagnostics}
    assert {"STL_UNITS_ASSUMED_MM", "TESSELLATED_GEOMETRY", "STL_FEATURES_NOT_RECOGNIZED"} <= codes
    assert ir.features == []  # never guessed from a mesh in milestone 1


def test_open_stl_reports_not_watertight(tmp_path):
    lines = ASCII_CUBE.split("  facet")
    p = tmp_path / "open.stl"
    p.write_text("  facet".join(lines[:-2]) + "endsolid cube\n")  # drop two facets
    ir, _ = analyze_file(p, SourceFormat.STL, with_preview=False)
    assert not ir.bodies[0].is_closed
    assert ir.mass_properties.volume is None
    assert "STL_NOT_WATERTIGHT" in {d.code for d in ir.diagnostics}
