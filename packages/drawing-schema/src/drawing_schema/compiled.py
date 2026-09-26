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


class FrameCell(StrictModel):
    """One compartment of a feature control frame."""

    symbol: str | None = Field(default=None, description="GD&T characteristic name (drawn as a vector symbol)")
    text: str | None = None
    diameter: bool = False  # Ø prefix
    modifier: str | None = Field(default=None, description="MMC / LMC (drawn as a circled M / L)")
    width: float


class FrameSpec(StrictModel):
    cells: list[FrameCell]
    height: float = 7.0

    @property
    def width(self) -> float:
        return sum(c.width for c in self.cells)


class ToleranceText(StrictModel):
    kind: str  # SYMMETRIC | DEVIATION | LIMITS | FIT
    upper: str
    lower: str = ""
    fit: str = ""  # FIT: the ISO 286 tolerance class printed before the deviations (e.g. H7)


class Stamp(StrictModel):
    """A boxed release stamp (e.g. NOT FOR MANUFACTURE) above the title-block column."""

    text: str
    rect: Rect


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
    # user-supplied manufacturing annotations attached to this dimension / callout
    tolerance: ToleranceText | None = None
    inspection: bool = False
    basic: bool = Field(default=False, description="theoretically exact dimension (framed)")
    frames: list[FrameSpec] = Field(default_factory=list)
    frames_origin: Point2 | None = Field(default=None, description="top-left corner of the first frame")
    datum: str | None = None
    datum_box: Rect | None = None
    datum_line: list[Point2] = Field(default_factory=list, description="triangle base centre first, box last")
    extra_bbox: Rect | None = Field(default=None, description="area used by frames / datum symbol")
    finish: str | None = Field(default=None, description="surface texture of the dimensioned feature, e.g. Ra 0.8")
    finish_tip: Point2 | None = Field(default=None, description="point of the (upright) ISO 1302 symbol")


class PmiKind(StrEnum):
    FRAME_GROUP = "FRAME_GROUP"  # leader-directed feature control frame(s) and/or datum symbol on a face
    SURFACE_FINISH = "SURFACE_FINISH"


class PmiOp(StrictModel):
    id: str
    view_id: str
    kind: PmiKind
    tip: Point2 = Field(description="point on the face edge")
    direction: Point2 = Field(description="unit outward direction (sheet)")
    leader: list[Point2] = Field(default_factory=list)
    arrow: bool = True  # frames: arrowhead on the face; datum only: filled datum triangle
    frames: list[FrameSpec] = Field(default_factory=list)
    frames_origin: Point2 | None = None
    datum: str | None = None
    datum_box: Rect | None = None
    text: str | None = None
    bbox: Rect
    target: str


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
    pmi: list[PmiOp] = Field(default_factory=list)
    zones: tuple[int, int] = Field(default=(8, 6), description="ISO 5457 grid: columns, rows")
    sheet_notes: list[str] = Field(default_factory=list, description="numbered notes printed above the title block")
    notes_rect: Rect | None = None
    notes_split: int | None = Field(default=None, description="two-column notes: index of the first right-column line")
    revision_rows: list[list[str]] = Field(default_factory=list)
    revision_rect: Rect | None = None
    stamp: Stamp | None = None
    notes: list[str] = Field(default_factory=list, description="compiler notes (not printed)")
    dropped_candidates: list[str] = Field(default_factory=list, description="not placed (reason in notes)")
