"""Shared enums and value types used by every CAD Drawing AI contract.

Coordinates and lengths are millimetres; angles are degrees unless a field name
says otherwise.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Confidence",
    "Diagnostic",
    "Severity",
    "SourceFormat",
    "Representation",
    "Vec3",
    "StrictModel",
    "InfoSource",
]


class StrictModel(BaseModel):
    """Base for all contract models: unknown fields are rejected, values are immutable."""

    # serialized fields with defaults are always present -> "required" in the exported schema
    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_serialization_defaults_required=True)


Vec3 = tuple[float, float, float]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class SourceFormat(StrEnum):
    STEP = "STEP"
    STL = "STL"


class Representation(StrEnum):
    """How much the geometry can be trusted."""

    EXACT_BREP = "EXACT_BREP"  # analytic B-Rep (STEP)
    TESSELLATED = "TESSELLATED"  # triangle mesh (STL): all values inferred


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class InfoSource(StrEnum):
    """Where a piece of engineering information came from."""

    USER = "USER"
    CAD_MODEL = "CAD_MODEL"
    DEFAULT = "DEFAULT"  # a documented default rule set (e.g. ISO 2768-mK), applied deterministically


class Diagnostic(StrictModel):
    code: str
    severity: Severity
    message: str
    entity_ids: list[str] = Field(default_factory=list)
