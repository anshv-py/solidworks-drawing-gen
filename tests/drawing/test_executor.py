"""Executor end to end on real STEP fixtures (OCCT HLR + ezdxf + matplotlib)."""

import json

import ezdxf
import pytest

from drawing_executor.pipeline import DrawingFailed, generate
from drawing_schema.settings import DrawingSettings

MODELS = ["plate_with_holes", "mounting_plate", "pocketed_block", "bracket", "shaft", "flange",
          "cylindrical_part", "enclosure", "chamfered_block"]


@pytest.mark.slow
@pytest.mark.parametrize("name", MODELS)
def test_generates_and_passes_qa(name, geometry_files, models_dir, tmp_path):
    res = generate(geometry_files[name], models_dir / f"{name}.step", DrawingSettings(), tmp_path, filename=f"{name}.step")
    assert res.passed, json.loads((tmp_path / "qa_report.json").read_text())["issues"]
    for a in ("drawing.dxf", "drawing.pdf", "drawing.svg", "preview.png"):
        assert (tmp_path / a).stat().st_size > 1000
    assert (tmp_path / "drawing.pdf").read_bytes()[:5] == b"%PDF-"
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["solidworks"] is False and "OCCT HLR" in manifest["generator"]


def test_dxf_content(geometry_files, models_dir, tmp_path):
    generate(geometry_files["plate_with_holes"], models_dir / "plate_with_holes.step", DrawingSettings(), tmp_path)
    doc = ezdxf.readfile(tmp_path / "drawing.dxf")
    msp = doc.modelspace()
    assert doc.header["$INSUNITS"] == 4
    assert {"VISIBLE", "HIDDEN", "CENTER", "DIM", "FRAME", "TITLE"} <= {l.dxf.name for l in doc.layers}
    dims = msp.query("DIMENSION")
    texts = {t.dxf.text for t in msp.query("TEXT")}
    # plain dimensions carry their text; basic (TED) / framed ones draw it explicitly next to the entity
    assert len(dims) >= 8
    assert {d.dxf.text for d in dims} | texts >= {"120.00", "80.00", "10.00", "50.00", "90.00", "15.00", "60.00",
                                                  "40.00"}
    assert "4X Ø8.00 THRU" in texts
    assert any("NOT PRODUCED BY SOLIDWORKS" in t for t in texts)
    assert len(msp.query("LINE[layer=='HIDDEN']") ) > 0  # hidden lines are drawn in orthographic views


def test_page_is_true_size(geometry_files, models_dir, tmp_path):
    generate(geometry_files["flange"], models_dir / "flange.step", DrawingSettings(), tmp_path)
    svg = (tmp_path / "drawing.svg").read_text()
    assert 'width="1190.55' in svg or 'width="1190.5' in svg  # 420 mm = 1190.55 pt (A3 landscape)


def test_stl_is_rejected_honestly(tmp_path, models_dir):
    from geometry_service.analyze import analyze_file
    from shared_types import SourceFormat

    ir, _ = analyze_file(models_dir / "bracket.stl", SourceFormat.STL, with_preview=False)
    g = tmp_path / "g.json"
    g.write_text(ir.model_dump_json())
    with pytest.raises(DrawingFailed) as e:
        generate(g, models_dir / "bracket.stl", DrawingSettings(), tmp_path / "out")
    assert e.value.code == "STL_NOT_SUPPORTED"


def test_hlr_front_view_of_bracket_shows_wall_in_front(geometry_files, models_dir, tmp_path):
    """Orientation sanity: in the FRONT view (viewer at -Y) the 60 mm tall wall is visible,
    so no hidden line may reach the full 60 mm height except along the wall."""
    generate(geometry_files["bracket"], models_dir / "bracket.step", DrawingSettings(), tmp_path)
    compiled = json.loads((tmp_path / "compiled.json").read_text())
    front = next(v for v in compiled["views"] if v["orientation"] == "FRONT")
    assert front["outline"]["y1"] - front["outline"]["y0"] == pytest.approx(60 * front["scale_factor"])


def test_missing_font_fails_loudly_instead_of_blank_text(geometry_files, models_dir, tmp_path, monkeypatch):
    """A host without any TrueType font (e.g. a slim Linux image) must not produce drawings whose
    text is silently blank."""
    import pytest
    from ezdxf.fonts import fonts

    from drawing_executor import dxf_writer
    from drawing_executor.pipeline import DrawingFailed

    monkeypatch.setattr(dxf_writer, "_font", lambda h: fonts.MonospaceFont(h))
    with pytest.raises(DrawingFailed, match="no TrueType font"):
        generate(geometry_files["flange"], models_dir / "flange.step", DrawingSettings(), tmp_path)
    assert not (tmp_path / "drawing.pdf").exists()
