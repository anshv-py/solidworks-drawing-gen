import pytest
from pydantic import ValidationError

from geometry_schema import GeometryIR, HoleFeature


def test_roundtrip_json(analyzed):
    ir, _ = analyzed["flange"]
    again = GeometryIR.model_validate_json(ir.model_dump_json())
    assert again == ir


def test_contract_is_strict(analyzed):
    ir, _ = analyzed["plate_with_holes"]
    data = ir.model_dump(mode="json")
    data["invented_material"] = "steel"
    with pytest.raises(ValidationError):
        GeometryIR.model_validate(data)
    hole = next(f for f in ir.features if f.type == "HOLE").model_dump(mode="json")
    hole["confidence"] = 1.5
    with pytest.raises(ValidationError):
        HoleFeature.model_validate(hole)


def test_feature_union_discriminates(analyzed):
    ir, _ = analyzed["mounting_plate"]
    kinds = {type(f).__name__ for f in ir.features}
    assert {"HoleFeature", "FilletFeature", "PatternFeature"} <= kinds
