"""DrawingPlan - the typed drawing intent produced by the planner (LLM or rules).

A DrawingPlan contains *decisions* (which views, which dimension candidates,
which annotations). It never contains geometric values: dimension values are
looked up from GeometryIR by the compiler via ``candidate_id``. Engineering
information (material, tolerances, GD&T ...) is ``UNSPECIFIED`` unless supplied
by the user or the CAD model, and always records its source.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, field_validator, model_validator

from drawing_schema.pmi import GeneralNotes, ManufacturingAnnotations
from shared_types import InfoSource, StrictModel

SCHEMA_VERSION = "0.1.0"

__all__ = [
    "SCHEMA_VERSION",
    "DrawingPlan",
    "DrawingKind",
    "DrawingStandard",
    "ProjectionMethod",
    "SheetSize",
    "SheetOrientation",
    "Sheet",
    "SHEET_SIZES_MM",
    "ViewOrientation",
    "DisplayStyle",
    "ViewFrame",
    "ViewSpec",
    "SectionView",
    "SectionPlane",
    "DetailView",
    "DimensionPreferences",
    "DimensionSelection",
    "AnnotationPreferences",
    "EngineeringField",
    "EngineeringInformation",
    "TitleBlock",
    "PlanUncertainty",
    "GeometryReference",
    "ISO_5455_SCALES",
    "DRAWING_SCALES",
    "ScaleSystem",
    "scale_series",
    "default_plan",
]


class DrawingKind(StrEnum):
    GEOMETRY = "GEOMETRY"  # shape only - no tolerances/material unless supplied
    MANUFACTURING = "MANUFACTURING"  # requires supplied engineering information


class DrawingStandard(StrEnum):
    ISO = "ISO"
    ASME = "ASME"


class ProjectionMethod(StrEnum):
    FIRST_ANGLE = "FIRST_ANGLE"
    THIRD_ANGLE = "THIRD_ANGLE"


class SheetSize(StrEnum):
    A0 = "A0"
    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    A4 = "A4"


# ISO 216, landscape (width, height) in mm
SHEET_SIZES_MM: dict[SheetSize, tuple[float, float]] = {
    SheetSize.A0: (1189.0, 841.0),
    SheetSize.A1: (841.0, 594.0),
    SheetSize.A2: (594.0, 420.0),
    SheetSize.A3: (420.0, 297.0),
    SheetSize.A4: (297.0, 210.0),
}


class SheetOrientation(StrEnum):
    LANDSCAPE = "LANDSCAPE"
    PORTRAIT = "PORTRAIT"


class ViewOrientation(StrEnum):
    FRONT = "FRONT"
    BACK = "BACK"
    TOP = "TOP"
    BOTTOM = "BOTTOM"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    ISOMETRIC = "ISOMETRIC"
    DIMETRIC = "DIMETRIC"
    TRIMETRIC = "TRIMETRIC"


PICTORIAL = {ViewOrientation.ISOMETRIC, ViewOrientation.DIMETRIC, ViewOrientation.TRIMETRIC}

# ISO 5455 recommended scales (1:1, reductions, enlargements; x10 multiples).
ISO_5455_SCALES: tuple[str, ...] = (
    "50:1", "20:1", "10:1", "5:1", "2:1", "1:1",
    "1:2", "1:5", "1:10", "1:20", "1:50", "1:100", "1:200", "1:500", "1:1000",
)
# Scales the layout may use, large -> small: ISO 5455 plus the common intermediate steps (so views can
# fill the sheet between 1:1 and 1:2 etc.). A non-ISO scale is reported by QA (MINOR), not rejected.
DRAWING_SCALES: tuple[str, ...] = (
    "50:1", "20:1", "10:1", "5:1", "4:1", "3:1", "2:1", "1.5:1", "1:1",
    "1:1.5", "1:2", "1:2.5", "1:3", "1:4", "1:5", "1:7.5", "1:10", "1:15", "1:20", "1:25", "1:50",
    "1:100", "1:200", "1:500", "1:1000",
)
_SCALE_RE = re.compile(r"^\d+(\.\d+)?:\d+(\.\d+)?$")


def _check_scale(value: str) -> str:
    if value == "AUTO":
        return value
    if not _SCALE_RE.match(value) or value not in DRAWING_SCALES:
        raise ValueError(f"scale must be 'AUTO' or one of {DRAWING_SCALES}, got {value!r}")
    return value


Scale = Annotated[str, AfterValidator(_check_scale)]


class ScaleSystem(StrEnum):
    """Scales the layout may choose from when the scale is AUTO."""

    ISO_5455 = "ISO_5455"  # preferred scales only (1:1, 1:2, 1:5, 1:10 ...)
    INTERMEDIATE = "INTERMEDIATE"  # ISO 5455 plus the common intermediate steps (1:1.5, 1:2.5, 1:3, 1:4 ...)


def scale_series(system: "ScaleSystem") -> tuple[str, ...]:
    """Scales of a system, large -> small."""
    return ISO_5455_SCALES if system == ScaleSystem.ISO_5455 else DRAWING_SCALES


class Sheet(StrictModel):
    size: SheetSize = SheetSize.A3
    orientation: SheetOrientation = SheetOrientation.LANDSCAPE
    scale: Scale = Field(default="AUTO", description="scale of the orthographic views; AUTO = the largest "
                         "scale of scale_system at which the layout fits")
    pictorial_scale: Scale = Field(default="AUTO", description="scale of the isometric view; AUTO = the "
                                   "smallest scale that draws it larger than the orthographic views")
    scale_system: ScaleSystem = Field(default=ScaleSystem.INTERMEDIATE,
                                      description="scales AUTO chooses from (a chosen scale may be any supported one)")

    def dimensions_mm(self) -> tuple[float, float]:
        w, h = SHEET_SIZES_MM[self.size]
        return (w, h) if self.orientation == SheetOrientation.LANDSCAPE else (h, w)


class ViewFrame(StrEnum):
    """Which model axis points up in the drawing views.

    Z_UP: front view looks along +Y (common for Creo/NX/Inventor/Fusion exports).
    Y_UP: front view looks along -Z (SolidWorks' native frame: Front = XY plane).
    """

    Z_UP = "Z_UP"
    Y_UP = "Y_UP"


class DisplayStyle(StrEnum):
    HIDDEN_LINES_REMOVED = "HIDDEN_LINES_REMOVED"
    HIDDEN_LINES_VISIBLE = "HIDDEN_LINES_VISIBLE"
    SHADED_WITH_EDGES = "SHADED_WITH_EDGES"


class ViewSpec(StrictModel):
    id: str
    orientation: ViewOrientation
    scale: Scale = "AUTO"
    display_style: DisplayStyle = DisplayStyle.HIDDEN_LINES_REMOVED
    dimensioned: bool = True

    @model_validator(mode="after")
    def _pictorial_not_dimensioned(self) -> Self:
        if self.orientation in PICTORIAL and self.dimensioned:
            raise ValueError("pictorial views (isometric/dimetric/trimetric) must not be dimensioned")
        return self


class SectionPlane(StrictModel):
    """Cutting plane defined only by references into GeometryIR - never by coordinates."""

    through_feature_id: str | None = Field(
        default=None, description="plane contains this feature's axis (holes, bosses)"
    )
    principal_plane: Literal["XY", "YZ", "XZ"] | None = Field(
        default=None, description="model principal plane through the bounding-box centre"
    )

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.through_feature_id is None) == (self.principal_plane is None):
            raise ValueError("exactly one of through_feature_id / principal_plane is required")
        return self


class SectionView(StrictModel):
    id: str
    label: str = Field(pattern=r"^[A-Z]{1,2}$")
    parent_view_id: str
    plane: SectionPlane
    scale: Scale = "AUTO"


class DetailView(StrictModel):
    id: str
    label: str = Field(pattern=r"^[A-Z]{1,2}$")
    parent_view_id: str
    feature_id: str = Field(description="region is centred on this GeometryIR feature")
    scale: Scale


class DimensionPreferences(StrictModel):
    overall: bool = True
    feature: bool = True
    holes: bool = True
    radii: bool = True
    diameters: bool = True
    angles: bool = True
    depths: bool = True
    decimal_places: int = Field(default=2, ge=0, le=4)
    trailing_zeros: bool = Field(default=True, description="8.00 rather than 8 (SolidWorks-style)")


class DimensionSelection(StrictModel):
    """Selects a dimension candidate (produced deterministically from GeometryIR) for a view.

    There is intentionally no value field: values come from GeometryIR only.
    """

    candidate_id: str
    view_id: str


class AnnotationPreferences(StrictModel):
    center_marks: bool = True
    centerlines: bool = True
    hole_callouts: bool = True


class EngineeringField(StrictModel):
    status: Literal["SPECIFIED", "UNSPECIFIED"] = "UNSPECIFIED"
    value: str | None = None
    source: InfoSource | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.status == "SPECIFIED":
            if not self.value or self.source is None:
                raise ValueError("SPECIFIED engineering information needs a value and a source")
        elif self.value is not None or self.source is not None:
            raise ValueError("UNSPECIFIED engineering information must not carry a value or source")
        return self


def _unspecified() -> EngineeringField:
    return EngineeringField()


class EngineeringInformation(StrictModel):
    material: EngineeringField = Field(default_factory=_unspecified)
    general_tolerance: EngineeringField = Field(default_factory=_unspecified)
    linear_tolerance: EngineeringField = Field(default_factory=_unspecified)
    angular_tolerance: EngineeringField = Field(default_factory=_unspecified)
    gdt: EngineeringField = Field(default_factory=_unspecified)
    datum_scheme: EngineeringField = Field(default_factory=_unspecified)
    surface_finish: EngineeringField = Field(default_factory=_unspecified)
    heat_treatment: EngineeringField = Field(default_factory=_unspecified)
    coating: EngineeringField = Field(default_factory=_unspecified)
    inspection_requirements: EngineeringField = Field(default_factory=_unspecified)
    manufacturing_process: EngineeringField = Field(default_factory=_unspecified)


def missing_manufacturing_information(info: "EngineeringInformation") -> list[str]:
    """A manufacturing drawing needs a material and a general (or linear) tolerance."""
    missing = []
    if info.material.status != "SPECIFIED":
        missing.append("material")
    if info.general_tolerance.status != "SPECIFIED" and info.linear_tolerance.status != "SPECIFIED":
        missing.append("general_tolerance")
    return missing


class TitleBlock(StrictModel):
    """Identification data - all user-supplied (never generated)."""

    title: str | None = Field(default=None, max_length=60)
    part_number: str | None = Field(default=None, max_length=40)
    drawing_number: str | None = Field(default=None, max_length=40)
    revision: str | None = Field(default=None, max_length=4)
    organization: str | None = Field(default=None, max_length=60)
    weight: str | None = Field(default=None, max_length=20, description="as stated by the user, e.g. '475 g'")
    quantity: str | None = Field(default=None, max_length=10)
    drawn_by: str | None = Field(default=None, max_length=30)
    drawn_date: str | None = Field(default=None, max_length=20)
    checked_by: str | None = Field(default=None, max_length=30)
    checked_date: str | None = Field(default=None, max_length=20)
    approved_by: str | None = Field(default=None, max_length=30)
    approved_date: str | None = Field(default=None, max_length=20)
    mfg_by: str | None = Field(default=None, max_length=30)
    mfg_date: str | None = Field(default=None, max_length=20)
    qa_by: str | None = Field(default=None, max_length=30)
    qa_date: str | None = Field(default=None, max_length=20)


class PlanUncertainty(StrictModel):
    message: str
    related_ids: list[str] = Field(default_factory=list)


class GeometryReference(StrictModel):
    source_sha256: str
    geometry_schema_version: str


class DrawingPlan(StrictModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    geometry: GeometryReference
    drawing_kind: DrawingKind = DrawingKind.GEOMETRY
    drawing_standard: DrawingStandard = DrawingStandard.ISO
    projection_method: ProjectionMethod = ProjectionMethod.FIRST_ANGLE
    sheet: Sheet = Sheet()
    units: Literal["mm"] = "mm"
    view_frame: ViewFrame = ViewFrame.Z_UP
    orthographic_display_style: DisplayStyle = DisplayStyle.HIDDEN_LINES_VISIBLE
    primary_view: ViewSpec = ViewSpec(
        id="V-PRIMARY", orientation=ViewOrientation.ISOMETRIC, dimensioned=False
    )
    projected_views: list[ViewOrientation] = Field(
        default_factory=lambda: [ViewOrientation.FRONT, ViewOrientation.TOP, ViewOrientation.RIGHT],
        description="orthographic views, placed relative to FRONT per projection_method",
    )
    sections: list[SectionView] = Field(default_factory=list)
    detail_views: list[DetailView] = Field(default_factory=list)
    dimensions: DimensionPreferences = DimensionPreferences()
    dimension_selections: list[DimensionSelection] = Field(
        default_factory=list,
        description="explicit candidate choices; empty = deterministic engine selects per preferences",
    )
    annotations: AnnotationPreferences = AnnotationPreferences()
    engineering_information: EngineeringInformation = EngineeringInformation()
    title_block: TitleBlock = TitleBlock()
    manufacturing: ManufacturingAnnotations = ManufacturingAnnotations()
    general_notes: GeneralNotes = GeneralNotes()
    pictorial_style: DisplayStyle = DisplayStyle.SHADED_WITH_EDGES
    uncertainties: list[PlanUncertainty] = Field(default_factory=list)
    rationale: str | None = Field(default=None, max_length=2000)
    rule_set: str | None = Field(default=None, description="id and version of the rule set that planned the drawing")
    feature_roles: list["RoleAssignment"] = Field(default_factory=list)
    view_triggers: list["ViewTrigger"] = Field(default_factory=list)
    cad_metadata_applied: list[str] = Field(
        default_factory=list, description="title-block fields taken from the CAD file, with their origin")
    rule_notes: list[str] = Field(default_factory=list, max_length=8,
                                  description="sheet notes required by a rule (e.g. THICKNESS of a one-view part)")

    @field_validator("projected_views")
    @classmethod
    def _orthographic_unique(cls, v: list[ViewOrientation]) -> list[ViewOrientation]:
        if len(set(v)) != len(v):
            raise ValueError("projected_views must not repeat an orientation")
        if PICTORIAL.intersection(v):
            raise ValueError("projected_views must be orthographic")
        return v

    @model_validator(mode="after")
    def _manufacturing_requires_information(self) -> Self:
        if self.drawing_kind == DrawingKind.MANUFACTURING:
            info = self.engineering_information
            missing = missing_manufacturing_information(info)
            if missing:
                raise ValueError(
                    "a MANUFACTURING drawing requires supplied engineering information: "
                    + ", ".join(missing)
                )
        view_ids = {self.primary_view.id} | {s.id for s in self.sections} | {
            d.id for d in self.detail_views
        } | {f"V-{o.value}" for o in self.projected_views}
        for ref in [s.parent_view_id for s in self.sections] + [
            d.parent_view_id for d in self.detail_views
        ] + [d.view_id for d in self.dimension_selections]:
            if ref not in view_ids:
                raise ValueError(f"unknown view id {ref!r}; known: {sorted(view_ids)}")
        return self


def default_plan(source_sha256: str, geometry_schema_version: str = "0.1.0") -> DrawingPlan:
    """The product defaults: ISO, first angle, A3 landscape, mm, isometric primary view."""
    return DrawingPlan(
        geometry=GeometryReference(
            source_sha256=source_sha256, geometry_schema_version=geometry_schema_version
        )
    )


from drawing_schema.roles import RoleAssignment, ViewTrigger  # noqa: E402  (roles imports pmi only)

DrawingPlan.model_rebuild()
