"""CompiledDrawing (a.k.a. DrawingOps): the deterministic, executor-neutral sheet description.

Consumed by an executor (open-source OCCT/ezdxf executor today, SolidWorks worker later).
All sheet coordinates are millimetres, origin at the bottom-left corner of the sheet.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from drawing_schema import (
    DisplayStyle,
    DrawingKind,
    DrawingStandard,
    ProjectionMethod,
    SheetOrientation,
    SheetSize,
    ViewOrientation,
)
from shared_types import StrictModel, Vec3

Point2 = tuple[float, float]


class Rect(StrictModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    def intersects(self, other: "Rect", clearance: float = 0.0) -> bool:
        return not (
            self.x1 + clearance <= other.x0
            or other.x1 + clearance <= self.x0
            or self.y1 + clearance <= other.y0
            or other.y1 + clearance <= self.y0
        )

    def inside(self, other: "Rect") -> bool:
        return self.x0 >= other.x0 and self.y0 >= other.y0 and self.x1 <= other.x1 and self.y1 <= other.y1

    def union(self, other: "Rect") -> "Rect":
        return Rect(
            x0=min(self.x0, other.x0), y0=min(self.y0, other.y0),
            x1=max(self.x1, other.x1), y1=max(self.y1, other.y1),
        )


class CompiledView(StrictModel):
    id: str
    orientation: ViewOrientation
    pictorial: bool
    eye: Vec3 = Field(description="unit vector from the part toward the viewer (model coords)")
    x_axis: Vec3 = Field(description="model direction drawn to the right")
    y_axis: Vec3 = Field(description="model direction drawn upward")
    scale: str
    scale_factor: float
    model_center: Vec3 = Field(description="model point placed at sheet_center")
    sheet_center: Point2
    outline: Rect = Field(description="sheet bbox of the projected part (from GeometryIR bbox)")
    display_style: DisplayStyle
    label: str | None = None


class DimensionOpKind(StrEnum):
    LINEAR = "LINEAR"
    LEADER_NOTE = "LEADER_NOTE"


class DimensionOp(StrictModel):
    id: str = Field(description="candidate id - the link back to GeometryIR")
    view_id: str
    kind: DimensionOpKind
    text: str
    value: float
    # LINEAR
    p1: Point2 | None = None
    p2: Point2 | None = None
    line_at: float | None = Field(default=None, description="dimension line position (y for horizontal, x for vertical)")
    horizontal: bool | None = None
    snap: list[bool] = Field(
        default_factory=lambda: [True, True],
        description="per extension origin: start at the nearest drawn edge (False = keep, e.g. a centre)",
    )
    # LEADER_NOTE
    leader: list[Point2] = Field(default_factory=list, description="arrow tip first")
    text_at: Point2 | None = None
    text_height: float = 3.5
    text_bbox: Rect
    feature_ids: list[str] = Field(default_factory=list)


class AnnotationKind(StrEnum):
    CENTER_MARK = "CENTER_MARK"
    CENTERLINE = "CENTERLINE"
    PITCH_CIRCLE = "PITCH_CIRCLE"


class AnnotationOp(StrictModel):
    id: str
    view_id: str
    kind: AnnotationKind
    points: list[Point2] = Field(default_factory=list)
    center: Point2 | None = None
    radius: float | None = None
    feature_ids: list[str] = Field(default_factory=list)


class TitleBlockField(StrictModel):
    label: str
    value: str


class CompiledDrawing(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    source_sha256: str
    drawing_kind: DrawingKind
    standard: DrawingStandard
    projection_method: ProjectionMethod
    sheet_size: SheetSize
    sheet_orientation: SheetOrientation
    sheet_w: float
    sheet_h: float
    frame: Rect
    title_block: Rect
    scale: str
    views: list[CompiledView]
    dimensions: list[DimensionOp]
    annotations: list[AnnotationOp]
    title_fields: list[TitleBlockField]
    notes: list[str] = Field(default_factory=list)
    dropped_candidates: list[str] = Field(default_factory=list, description="not placed (reason in notes)")
