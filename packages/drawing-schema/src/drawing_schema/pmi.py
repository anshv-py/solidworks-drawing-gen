"""User-supplied manufacturing annotations (PMI): datums, GD&T, tolerances, threads, finish, notes.

None of this can be derived from CAD geometry, so the application never generates it: every
item here is entered by a person (source = USER) and is attached to a real GeometryIR face or
feature. Validation enforces GD&T grammar (e.g. form tolerances take no datums, orientation
tolerances need one) and referential integrity; the planner additionally checks that every
target id exists in the part's GeometryIR.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from shared_types import InfoSource, StrictModel

# ASME Y14.5 / ISO 5459 practice: I, O and Q are not used as datum letters.
DATUM_LETTER = r"^[A-HJ-NPR-Z]$"


class GdtCharacteristic(StrEnum):
    STRAIGHTNESS = "STRAIGHTNESS"
    FLATNESS = "FLATNESS"
    CIRCULARITY = "CIRCULARITY"
    CYLINDRICITY = "CYLINDRICITY"
    PROFILE_OF_A_LINE = "PROFILE_OF_A_LINE"
    PROFILE_OF_A_SURFACE = "PROFILE_OF_A_SURFACE"
    ANGULARITY = "ANGULARITY"
    PERPENDICULARITY = "PERPENDICULARITY"
    PARALLELISM = "PARALLELISM"
    POSITION = "POSITION"
    CONCENTRICITY = "CONCENTRICITY"
    SYMMETRY = "SYMMETRY"
    CIRCULAR_RUNOUT = "CIRCULAR_RUNOUT"
    TOTAL_RUNOUT = "TOTAL_RUNOUT"


FORM = {GdtCharacteristic.STRAIGHTNESS, GdtCharacteristic.FLATNESS, GdtCharacteristic.CIRCULARITY,
        GdtCharacteristic.CYLINDRICITY}
NEEDS_DATUM = {GdtCharacteristic.ANGULARITY, GdtCharacteristic.PERPENDICULARITY, GdtCharacteristic.PARALLELISM,
               GdtCharacteristic.CONCENTRICITY, GdtCharacteristic.SYMMETRY, GdtCharacteristic.CIRCULAR_RUNOUT,
               GdtCharacteristic.TOTAL_RUNOUT}
DIAMETER_ZONE_ALLOWED = {GdtCharacteristic.POSITION, GdtCharacteristic.STRAIGHTNESS,
                         GdtCharacteristic.PERPENDICULARITY, GdtCharacteristic.PARALLELISM,
                         GdtCharacteristic.ANGULARITY, GdtCharacteristic.CONCENTRICITY}
MODIFIER_ALLOWED = {GdtCharacteristic.POSITION, GdtCharacteristic.STRAIGHTNESS,
                    GdtCharacteristic.PERPENDICULARITY, GdtCharacteristic.PARALLELISM,
                    GdtCharacteristic.ANGULARITY}


class MaterialCondition(StrEnum):
    MMC = "MMC"  # Ⓜ
    LMC = "LMC"  # Ⓛ


class Target(StrictModel):
    """A GeometryIR feature (hole, boss, pattern, slot, pocket …) or a single face."""

    feature_id: str | None = None
    face_id: str | None = None

    @model_validator(mode="after")
    def _one(self) -> Self:
        if (self.feature_id is None) == (self.face_id is None):
            raise ValueError("a target needs exactly one of feature_id / face_id")
        return self

    @property
    def ref(self) -> str:
        return self.feature_id or self.face_id  # type: ignore[return-value]


class Datum(StrictModel):
    letter: str = Field(pattern=DATUM_LETTER)
    target: Target


class DatumReference(StrictModel):
    letter: str = Field(pattern=DATUM_LETTER)
    material_condition: MaterialCondition | None = None


class FeatureControlFrame(StrictModel):
    characteristic: GdtCharacteristic
    tolerance: float = Field(gt=0, le=100, description="tolerance zone size, mm")
    diameter_zone: bool = False
    material_condition: MaterialCondition | None = None
    datums: list[DatumReference] = Field(default_factory=list, max_length=3)
    target: Target

    @model_validator(mode="after")
    def _grammar(self) -> Self:
        c = self.characteristic
        if c in FORM and self.datums:
            raise ValueError(f"{c.value} is a form tolerance and cannot reference datums")
        if c in NEEDS_DATUM and not self.datums:
            raise ValueError(f"{c.value} requires at least one datum reference")
        if self.diameter_zone and c not in DIAMETER_ZONE_ALLOWED:
            raise ValueError(f"a diameter (Ø) zone is not applicable to {c.value}")
        if self.material_condition and c not in MODIFIER_ALLOWED:
            raise ValueError(f"MMC/LMC modifiers are not applicable to {c.value}")
        letters = [d.letter for d in self.datums]
        if len(set(letters)) != len(letters):
            raise ValueError("a datum may appear only once in a feature control frame")
        return self


class ToleranceKind(StrEnum):
    SYMMETRIC = "SYMMETRIC"  # 9.00 ±0.02
    DEVIATION = "DEVIATION"  # 8.00 +0.10 / 0.00  (stacked)
    LIMITS = "LIMITS"  # 8.10 / 8.00
    FIT = "FIT"  # Ø40.00 H7 +0.025 / 0.000  (ISO 286 tolerance class; deviations from the ISO 286 tables)


class DimensionTolerance(StrictModel):
    candidate_id: str
    kind: ToleranceKind
    upper: float = Field(description="SYMMETRIC: the ± value; DEVIATION/LIMITS: upper deviation")
    lower: float = Field(default=0.0, description="DEVIATION/LIMITS: lower deviation (signed)")
    fit: str | None = Field(default=None, pattern=r"^[A-Za-z]{1,2}\d{1,2}$",
                            description="FIT: ISO 286 tolerance class, e.g. H7 (hole) or h6 (shaft)")

    @model_validator(mode="after")
    def _order(self) -> Self:
        if (self.kind == ToleranceKind.FIT) != (self.fit is not None):
            raise ValueError("a FIT tolerance needs its ISO 286 class (and only a FIT tolerance has one)")
        if self.kind == ToleranceKind.SYMMETRIC and self.upper <= 0:
            raise ValueError("a symmetric tolerance must be > 0")
        if self.kind != ToleranceKind.SYMMETRIC and self.upper < self.lower:
            raise ValueError("upper deviation must be >= lower deviation")
        return self


class ThreadCallout(StrictModel):
    feature_id: str
    designation: str = Field(min_length=2, max_length=40, description="e.g. M8x1.25-6H (as specified by the user)")
    depth: float | None = Field(default=None, gt=0, description="thread depth; required for blind holes")
    source: InfoSource = Field(default=InfoSource.USER, description="DEFAULT: derived by the rule set from an "
                               "assumed tapped hole (thread depth of a blind hole assumed)")


class SurfaceFinishMark(StrictModel):
    target: Target
    ra_um: float = Field(gt=0, le=100)


class FeatureNote(StrictModel):
    target: Target
    text: str = Field(min_length=1, max_length=60)


class RevisionEntry(StrictModel):
    revision: str = Field(min_length=1, max_length=4)
    description: str = Field(default="", max_length=80)
    date: str = Field(default="", max_length=20)
    approved_by: str = Field(default="", max_length=30)


class ManufacturingAnnotations(StrictModel):
    datums: list[Datum] = Field(default_factory=list)
    frames: list[FeatureControlFrame] = Field(default_factory=list)
    tolerances: list[DimensionTolerance] = Field(default_factory=list)
    threads: list[ThreadCallout] = Field(default_factory=list)
    inspection_dimensions: list[str] = Field(default_factory=list, description="candidate ids marked for inspection")
    basic_dimensions: list[str] = Field(default_factory=list,
                                        description="candidate ids drawn as theoretically exact (boxed) dimensions")
    surface_finish_marks: list[SurfaceFinishMark] = Field(default_factory=list)
    feature_notes: list[FeatureNote] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, max_length=12)
    revisions: list[RevisionEntry] = Field(default_factory=list, max_length=12)
    deburr_break_sharp_edges: bool = Field(default=False, description="print the standard edge note (user choice)")

    @model_validator(mode="after")
    def _references(self) -> Self:
        letters = [d.letter for d in self.datums]
        if len(set(letters)) != len(letters):
            raise ValueError("datum letters must be unique")
        for f in self.frames:
            for d in f.datums:
                if d.letter not in letters:
                    raise ValueError(f"datum {d.letter} is referenced by a frame but not defined")
        ids = [t.candidate_id for t in self.tolerances]
        if len(set(ids)) != len(ids):
            raise ValueError("a dimension can carry only one tolerance")
        threads = [t.feature_id for t in self.threads]
        if len(set(threads)) != len(threads):
            raise ValueError("a hole can carry only one thread callout")
        return self

    @property
    def is_empty(self) -> bool:
        return not (self.datums or self.frames or self.tolerances or self.threads or self.inspection_dimensions
                    or self.basic_dimensions
                    or self.surface_finish_marks or self.feature_notes or self.notes or self.revisions
                    or self.deburr_break_sharp_edges)


class ManufacturingProcess(StrEnum):
    UNSPECIFIED = "UNSPECIFIED"
    CNC_MACHINED = "CNC_MACHINED"
    SHEET_METAL = "SHEET_METAL"
    CASTING = "CASTING"
    FORGING = "FORGING"
    WELDMENT = "WELDMENT"
    MOULDED = "MOULDED"
    ADDITIVE = "ADDITIVE"


class NotesStyle(StrEnum):
    CONCISE = "CONCISE"  # standard, units/projection, general tolerance, datum frame, TEDs, user notes
    FULL = "FULL"  # the full 15-note manufacturing checklist (unsupplied values print as [PLACEHOLDER])


class GeneralNotes(StrictModel):
    """The default numbered drawing notes (on by default).

    Notes are assembled deterministically from these user entries, the rest of the drawing
    settings and GeometryIR. Anything not supplied is printed as a [PLACEHOLDER] - never a
    guessed value.
    """

    enabled: bool = True
    style: NotesStyle = NotesStyle.CONCISE
    process: ManufacturingProcess = ManufacturingProcess.UNSPECIFIED
    general_geometric_tolerance: str | None = Field(default=None, max_length=80)
    edge_break: str | None = Field(default=None, max_length=40, description="sharp-edge break value, e.g. as specified")
    masked_surfaces: str | None = Field(default=None, max_length=80)
    thread_class: str | None = Field(default=None, max_length=40)
    process_sequence: str | None = Field(default=None, max_length=80,
                                         description="machining vs heat treatment / coating order")
    model_revision: str | None = Field(default=None, max_length=20)
    marking: str | None = Field(default=None, max_length=80)
    supplier_bullets: bool = Field(default=True, description='print "WHAT THE SUPPLIER MUST NOT ASSUME"')
