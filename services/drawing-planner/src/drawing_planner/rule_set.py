"""The primary drawing rule set (rules/drawing_rules.yaml), validated on load.

The YAML is the executable form of the two owner-supplied documents kept next to it
(rules/manufacturing_drawing_rules.md, rules/manufacturing_drawing_reference_examples.md). Every value the
planner applies from the rule set comes from here; nothing is hard-coded twice.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from drawing_schema.pmi import GdtCharacteristic, ManufacturingProcess, MaterialCondition
from drawing_schema.roles import FeatureRole

RULES_DIR = Path(__file__).with_name("rules")
RULES_FILE = RULES_DIR / "drawing_rules.yaml"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleSetId(_M):
    id: str
    version: str


class Defaults(_M):
    drawing_standard: Literal["ISO", "ASME"]
    general_tolerance: str
    default_surface_finish_ra: float = Field(gt=0)
    fit_system: Literal["HOLE_BASIS", "SHAFT_BASIS"]
    fits: dict[str, str]


class IsometricTriggers(_M):
    nonorthogonal_face_count_gt: int
    processes: list[ManufacturingProcess]
    assembly_bodies_gt: int
    sheet_metal_bends_gt: int


class SectionTriggers(_M):
    blind_hole_depth_to_diameter_gt: float
    counterbore_or_countersink: bool
    stepped_coaxial_bores: bool


class DetailTriggers(_M):
    feature_size_on_sheet_lt_mm: float
    tight_tolerance_lt_mm: float
    tight_tolerance_scale_lt: float


class AuxiliaryTriggers(_M):
    feature_axis_not_principal: bool


class BreakTriggers(_M):
    length_to_width_ratio_gt: float


class Views(_M):
    minimal_orthographic: bool
    single_view_thickness_note: bool
    single_view_max_thickness_ratio: float = Field(gt=0, le=1)
    isometric_triggers: IsometricTriggers
    section_triggers: SectionTriggers
    detail_triggers: DetailTriggers
    auxiliary_triggers: AuxiliaryTriggers
    break_triggers: BreakTriggers


class BearingBoreInference(_M):
    min_diameter_mm: float
    ratio_to_other_holes: float


class ClearanceInference(_M):
    match_tolerance_mm: float
    iso_273: dict[str, list[float]]

    def match(self, diameter: float) -> tuple[str, float] | None:
        """(thread size, nominal fastener diameter) of the ISO 273 clearance hole nearest ``diameter``."""
        best = None
        for size, holes in self.iso_273.items():
            for h in holes:
                d = abs(h - diameter)
                if d <= self.match_tolerance_mm + 1e-9 and (best is None or d < best[0]):
                    best = (d, size)
        return None if best is None else (best[1], float(best[1][1:]))


class DowelInference(_M):
    diameters_mm: list[float]
    max_count: int


class ShaftInference(_M):
    length_to_diameter_ge: float


class TappedInference(_M):
    match_tolerance_mm: float
    min_engagement_ratio: float
    coarse: dict[str, list[float]]

    def match(self, diameter: float) -> tuple[str, float, float] | None:
        """(size, nominal, pitch) of the coarse thread whose tap drill is ``diameter``."""
        for size, (pitch, drill) in self.coarse.items():
            if abs(drill - diameter) <= self.match_tolerance_mm + 1e-9:
                return size, float(size[1:]), pitch
        return None

    def nominal(self, diameter: float) -> tuple[str, float, float] | None:
        """(size, nominal, pitch) of a hole modelled at the thread's nominal diameter."""
        for size, (pitch, _) in self.coarse.items():
            if abs(float(size[1:]) - diameter) <= self.match_tolerance_mm + 1e-9:
                return size, float(size[1:]), pitch
        return None


class Inference(_M):
    bearing_bore: BearingBoreInference
    clearance_holes: ClearanceInference
    dowel_holes: DowelInference
    shaft: ShaftInference
    tapped_holes: TappedInference


class FrameRule(_M):
    characteristic: GdtCharacteristic
    tolerance: float | Literal["ISO_2768_K"]
    datums: list[str] = Field(default_factory=list)
    diameter_zone: bool = False
    material_condition: MaterialCondition | None = None
    cap: Literal["FLOATING_FASTENER"] | None = None


class SizeTolerance(_M):
    upper: float
    lower: float


class Treatment(_M):
    rule: str
    datum: str | None = None
    fit: str | None = None
    size_tolerance: SizeTolerance | None = None
    frames: list[FrameRule] = Field(default_factory=list)
    depth_tolerance: SizeTolerance | None = None
    finish_ra: float | None = None
    note: str | None = None
    requires_thread_designation: bool = False
    thread_class: str | None = None
    blind_thread_depth: Literal["DRILL_DEPTH_MINUS_3P"] | None = None


class Roles(_M):
    inference: Inference
    treatments: dict[FeatureRole, Treatment]


class SheetMetalRules(_M):
    flat_pattern: bool
    bend_allowance: Literal["DIN_6935"]
    bend_angle_tolerance_deg: float


class Gate(_M):
    hard_blockers: list[int]
    warnings: list[int]
    stamp_text: str


class RuleSet(_M):
    rule_set: RuleSetId
    defaults: Defaults
    views: Views
    roles: Roles
    sheet_metal: SheetMetalRules
    gate: Gate

    @property
    def label(self) -> str:
        return f"{self.rule_set.id} {self.rule_set.version}"

    def treatment(self, role: FeatureRole) -> Treatment | None:
        return self.roles.treatments.get(role)


@cache
def load_rules(path: Path = RULES_FILE) -> RuleSet:
    return RuleSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


__all__ = ["RULES_DIR", "RULES_FILE", "FrameRule", "RuleSet", "Treatment", "load_rules"]
