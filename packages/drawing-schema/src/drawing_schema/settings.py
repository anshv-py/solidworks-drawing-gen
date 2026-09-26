"""User-facing drawing settings (API input). The planner turns these + GeometryIR into a DrawingPlan."""

from __future__ import annotations

from typing import Self

from pydantic import Field, field_validator, model_validator

from drawing_schema import (
    PICTORIAL,
    AnnotationPreferences,
    DimensionPreferences,
    DisplayStyle,
    DrawingKind,
    DrawingStandard,
    EngineeringInformation,
    ProjectionMethod,
    Sheet,
    TitleBlock,
    ViewFrame,
    ViewOrientation,
    missing_manufacturing_information,
)
from enum import StrEnum

from drawing_schema.pmi import GeneralNotes, ManufacturingAnnotations
from drawing_schema.roles import RoleOverride
from shared_types import StrictModel


class ViewSelection(StrEnum):
    RULES = "RULES"  # primary rule set: minimum orthographic views, isometric only when a trigger fires
    MANUAL = "MANUAL"  # exactly primary_view + projected_views as chosen


class DrawingSettings(StrictModel):
    drawing_kind: DrawingKind = DrawingKind.GEOMETRY
    drawing_standard: DrawingStandard = DrawingStandard.ISO
    projection_method: ProjectionMethod = ProjectionMethod.FIRST_ANGLE
    sheet: Sheet = Sheet()
    view_frame: ViewFrame = ViewFrame.Z_UP
    primary_view: ViewOrientation = ViewOrientation.ISOMETRIC
    projected_views: list[ViewOrientation] = Field(
        default_factory=lambda: [ViewOrientation.FRONT, ViewOrientation.TOP, ViewOrientation.RIGHT]
    )
    orthographic_display_style: DisplayStyle = DisplayStyle.HIDDEN_LINES_VISIBLE
    dimensions: DimensionPreferences = DimensionPreferences()
    annotations: AnnotationPreferences = AnnotationPreferences()
    title_block: TitleBlock = TitleBlock()
    engineering_information: EngineeringInformation = EngineeringInformation()
    manufacturing: ManufacturingAnnotations = ManufacturingAnnotations()
    general_notes: GeneralNotes = GeneralNotes()
    pictorial_style: DisplayStyle = DisplayStyle.SHADED_WITH_EDGES
    view_selection: ViewSelection = Field(
        default=ViewSelection.RULES,
        description="RULES: projected_views is the pool the rule set picks the minimum from, and the pictorial "
        "primary view is added only when an isometric trigger fires; MANUAL: views exactly as chosen",
    )
    feature_roles: list[RoleOverride] = Field(
        default_factory=list, description="user-set / confirmed functional roles, keyed by GeometryIR id")
    default_gdt: bool = Field(
        default=True,
        description="when no datums / GD&T are supplied, apply the default datum reference frame and ISO 2768-mK "
        "derived GD&T (drawing_planner.gdt_defaults)",
    )

    @field_validator("projected_views")
    @classmethod
    def _ortho(cls, v: list[ViewOrientation]) -> list[ViewOrientation]:
        if len(set(v)) != len(v) or PICTORIAL.intersection(v):
            raise ValueError("projected_views must be distinct orthographic views")
        if not v:
            raise ValueError("at least one orthographic view is required for dimensioning")
        return v

    @model_validator(mode="after")
    def _manufacturing_requires_information(self) -> Self:
        if self.drawing_kind == DrawingKind.MANUFACTURING:
            missing = missing_manufacturing_information(self.engineering_information)
            if missing:
                raise ValueError("a MANUFACTURING drawing requires supplied engineering information: "
                                 + ", ".join(missing))
        return self
