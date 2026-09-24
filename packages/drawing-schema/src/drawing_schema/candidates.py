"""Dimension candidates: every value is copied from GeometryIR by deterministic code."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from shared_types import StrictModel, Vec3


class CandidateKind(StrEnum):
    LINEAR = "LINEAR"  # distance between p1 and p2 measured along `direction`
    DIAMETER = "DIAMETER"  # Ø across a cylinder seen from the side (p1/p2 on opposite silhouettes)
    HOLE_CALLOUT = "HOLE_CALLOUT"  # leader note on the hole circle (seen along the axis)
    RADIUS = "RADIUS"  # leader note on an arc (seen along the axis)
    PCD = "PCD"  # pitch-circle diameter of a circular pattern (seen along the axis)
    CHAMFER = "CHAMFER"  # leader note on a chamfer (seen along its edge)


class ViewRule(StrEnum):
    """Which views can show the candidate in true size."""

    IN_PLANE = "IN_PLANE"  # `direction` lies in the view plane
    ALONG_AXIS = "ALONG_AXIS"  # the view looks along `axis` (circles appear as circles)
    ACROSS_AXIS = "ACROSS_AXIS"  # `axis` lies in the view plane (cylinders seen from the side)


class CandidateRole(StrEnum):
    OVERALL = "OVERALL"
    SIZE = "SIZE"
    LOCATION = "LOCATION"
    PITCH = "PITCH"
    DEPTH = "DEPTH"
    CALLOUT = "CALLOUT"


class DimensionCandidate(StrictModel):
    id: str
    kind: CandidateKind
    role: CandidateRole
    value: float = Field(description="mm (or deg); copied from GeometryIR, never computed by an LLM")
    text: str = Field(description="label as printed on the drawing")
    feature_ids: list[str] = Field(default_factory=list)
    source: str = Field(description="GeometryIR field(s) the value came from")
    view_rule: ViewRule
    priority: int = Field(description="lower = more important; also the redundancy-resolution order")
    # geometry in model coordinates (mm)
    p1: Vec3 | None = None
    p2: Vec3 | None = None
    direction: Vec3 | None = None
    center: Vec3 | None = None
    axis: Vec3 | None = None
    radius: float | None = None
    anchor: Vec3 | None = None
    count: int = 1
    anchors: tuple[str, str] = Field(
        default=("FACE", "FACE"),
        description="what p1/p2 are: FACE (a face/edge extreme) or CENTER:<feature> (an axis/centre)",
    )
