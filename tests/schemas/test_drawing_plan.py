import pytest
from pydantic import ValidationError

from drawing_schema import (
    DrawingPlan,
    EngineeringField,
    ViewSpec,
    default_plan,
)

SHA = "a" * 64


def test_product_defaults():
    p = default_plan(SHA)
    assert p.drawing_standard == "ISO"
    assert p.projection_method == "FIRST_ANGLE"
    assert (p.sheet.size, p.sheet.orientation) == ("A3", "LANDSCAPE")
    assert p.sheet.dimensions_mm() == (420.0, 297.0)
    assert p.units == "mm"
    assert p.primary_view.orientation == "ISOMETRIC" and p.primary_view.scale == "AUTO"
    assert p.projected_views == ["FRONT", "TOP", "RIGHT"]
    assert p.drawing_kind == "GEOMETRY"
    assert all(v for v in p.dimensions.model_dump().values() if isinstance(v, bool))
    assert p.annotations.center_marks and p.annotations.centerlines and p.annotations.hole_callouts


def test_engineering_information_is_unspecified_by_default():
    info = default_plan(SHA).engineering_information
    for name, field in info:
        assert field.status == "UNSPECIFIED" and field.value is None and field.source is None, name


def test_specified_information_requires_source():
    with pytest.raises(ValidationError):
        EngineeringField(status="SPECIFIED", value="S235JR")
    with pytest.raises(ValidationError):
        EngineeringField(status="UNSPECIFIED", value="S235JR")
    assert EngineeringField(status="SPECIFIED", value="S235JR", source="USER").value == "S235JR"


def test_manufacturing_drawing_requires_supplied_information():
    data = default_plan(SHA).model_dump()
    data["drawing_kind"] = "MANUFACTURING"
    with pytest.raises(ValidationError, match="material"):
        DrawingPlan.model_validate(data)
    data["engineering_information"]["material"] = {"status": "SPECIFIED", "value": "EN AW-6082", "source": "USER"}
    data["engineering_information"]["general_tolerance"] = {"status": "SPECIFIED", "value": "ISO 2768-mK", "source": "USER"}
    assert DrawingPlan.model_validate(data).drawing_kind == "MANUFACTURING"


def test_dimension_selection_cannot_carry_values():
    data = default_plan(SHA).model_dump()
    data["dimension_selections"] = [{"candidate_id": "DIM-OVERALL-X", "view_id": "V-FRONT", "value": 120.0}]
    with pytest.raises(ValidationError):
        DrawingPlan.model_validate(data)


def test_unknown_view_reference_rejected():
    data = default_plan(SHA).model_dump()
    data["dimension_selections"] = [{"candidate_id": "DIM-1", "view_id": "V-NOPE"}]
    with pytest.raises(ValidationError, match="unknown view"):
        DrawingPlan.model_validate(data)


@pytest.mark.parametrize("scale", ["1:7", "2.5:1", "abc", "3:7"])
def test_unsupported_scales_rejected(scale):
    with pytest.raises(ValidationError):
        ViewSpec(id="V", orientation="FRONT", scale=scale)


def test_pictorial_views_are_not_dimensioned():
    with pytest.raises(ValidationError):
        ViewSpec(id="V", orientation="ISOMETRIC", dimensioned=True)
    data = default_plan(SHA).model_dump()
    data["projected_views"] = ["FRONT", "ISOMETRIC"]
    with pytest.raises(ValidationError):
        DrawingPlan.model_validate(data)


def test_json_schema_export_is_strict():
    schema = DrawingPlan.model_json_schema()
    assert schema["additionalProperties"] is False
    assert "value" not in schema["$defs"]["DimensionSelection"]["properties"]
