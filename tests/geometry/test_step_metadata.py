"""CAD product data (STEP PRODUCT / version / MATERIAL_DESIGNATION / user-defined attributes) into the
title block, never overriding the user and never guessing."""

import pytest

from drawing_planner import plan_baseline
from drawing_planner.materials import density
from drawing_planner.rule_set import load_rules
from drawing_qa.compliance import build_compliance
from drawing_schema.settings import DrawingSettings
from geometry_service.step_metadata import read_step_metadata


def with_product_data(src, dst, *, product=("FL-100-X", "Cover flange", "flange for pump P3"), revision="B",
                      material="EN AW-6082 T6", attributes=None):
    """The fixture flange with product data written the way CAD exporters write it (AP214)."""
    text = src.read_text()
    text = text.replace("#6 = PRODUCT_DEFINITION_FORMATION('','',#7);",
                        f"#6 = PRODUCT_DEFINITION_FORMATION('{revision}','',#7);")
    old = "#7 = PRODUCT('Open CASCADE STEP translator 8.0 6',\n  'Open CASCADE STEP translator 8.0 6','',(#8));"
    assert old in text
    text = text.replace(old, "#7 = PRODUCT('{}','{}','{}',(#8));".format(*product))
    extra = []
    if material:
        extra.append(f"#90001 = MATERIAL_DESIGNATION('{material}',(#4));")
    attrs = attributes if attributes is not None else {
        "PartNo": "FL-100", "Mass": "0.475 kg", "Finish": '"SW-Finish@Part1.SLDPRT"',
        "Descri\\X2\\00E7\\X0\\ao": "tampa"}
    if attrs:
        refs = ",".join(f"#{90100 + k}" for k in range(len(attrs)))
        extra += ["#90002 = PROPERTY_DEFINITION('user defined attribute','',#5);",
                  "#90003 = PROPERTY_DEFINITION_REPRESENTATION(#90002,#90004);",
                  f"#90004 = REPRESENTATION('',({refs}),#959);"]
        extra += [f"#{90100 + k} = DESCRIPTIVE_REPRESENTATION_ITEM('{key}','{v}');"
                  for k, (key, v) in enumerate(attrs.items())]
    i = text.rindex("ENDSEC;")
    dst.write_text(text[:i] + "\n".join(extra) + "\n" + text[i:])
    return dst


def test_translator_placeholders_are_not_product_data(models_dir):
    meta = read_step_metadata(models_dir / "flange.step")
    assert meta.empty and meta.name is None and meta.part_number is None


def test_product_data_is_read_with_its_origin(models_dir, tmp_path):
    meta = read_step_metadata(with_product_data(models_dir / "flange.step", tmp_path / "f.step"))
    assert meta.name == "Cover flange" and meta.description == "flange for pump P3"
    assert meta.part_number == "FL-100"  # the explicit custom property wins over PRODUCT.id
    assert "user-defined attribute 'PartNo'" in meta.sources["part_number"]
    assert meta.revision == "B" and "PRODUCT_DEFINITION_FORMATION" in meta.sources["revision"]
    assert meta.material == "EN AW-6082 T6" and meta.sources["material"] == "STEP MATERIAL_DESIGNATION"
    assert meta.mass_g == pytest.approx(475.0)
    assert meta.attributes["Descriçao"] == "tampa"  # ISO 10303-21 \X2\ escape decoded
    assert "Finish" in meta.attributes  # kept for display ...
    # ... but an unevaluated SolidWorks link is never used as a value
    link = read_step_metadata(with_product_data(models_dir / "flange.step", tmp_path / "g.step", material=None,
                                                attributes={"Material": '"SW-Material@Part1.SLDPRT"'}))
    assert link.material is None


def test_product_id_equal_to_name_is_not_a_part_number(models_dir, tmp_path):
    meta = read_step_metadata(with_product_data(models_dir / "flange.step", tmp_path / "f.step",
                                                product=("flange", "flange", ""), attributes={}))
    assert meta.name == "flange" and meta.part_number is None


def test_metadata_fills_the_title_block_and_passes_the_gate(models_dir, tmp_path):
    from geometry_service.analyze import analyze_file
    from shared_types import SourceFormat

    ir, _ = analyze_file(with_product_data(models_dir / "flange.step", tmp_path / "f.step", attributes={}),
                         SourceFormat.STEP, with_preview=False)
    r = plan_baseline(ir, DrawingSettings())
    tb, eng = r.plan.title_block, r.plan.engineering_information
    assert (tb.title, tb.part_number, tb.revision) == ("Cover flange", "FL-100-X", "B")
    assert eng.material.value == "EN AW-6082 T6" and eng.material.source.value == "CAD_MODEL"
    # no mass in the file: exact volume x nominal aluminium density
    grams = ir.mass_properties.volume / 1000 * 2.70
    assert tb.weight == f"{grams:.0f} g (CALC.)"
    assert any("calculated" in a for a in r.plan.cad_metadata_applied)
    rules = load_rules()
    c = build_compliance(r.plan, ir, r.candidates, hard_blockers=rules.gate.hard_blockers)
    assert c.releasable and c.stamp is None
    assert any("from CAD: part number FL-100-X" in d for d in c.items[0].details)
    # the user's own values always win, and the import can be switched off
    mine = plan_baseline(ir, DrawingSettings.model_validate({"title_block": {"part_number": "MY-1", "weight": "1 kg"}}))
    assert mine.plan.title_block.part_number == "MY-1" and mine.plan.title_block.weight == "1 kg"
    off = plan_baseline(ir, DrawingSettings(use_cad_metadata=False))
    assert off.plan.title_block.part_number is None and off.plan.engineering_information.material.status == "UNSPECIFIED"


@pytest.mark.parametrize("material,rho", [("EN AW-6082 T6", 2.70), ("1.4301", 7.93), ("AISI 316L", 7.98),
                                          ("S355JR", 7.85), ("Ti-6Al-4V", 4.43), ("POM-C", 1.41),
                                          ("EN-GJS-400-15", 7.1), ("CuZn39Pb3 brass", 8.5)])
def test_density_table(material, rho):
    assert density(material)[0] == rho


def test_unknown_material_gives_no_weight():
    assert density("Unobtainium 42") is None
