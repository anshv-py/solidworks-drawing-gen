"""GeometryIR - the CAD-neutral geometry intermediate representation.

Every numerical value in this document is produced by the deterministic
geometry engine (OCCT). Nothing here may be authored by an LLM.

Conventions
-----------
* Lengths in millimetres, angles in degrees, areas mm^2, volumes mm^3.
* ``id`` fields are stable, content-derived identifiers (see GEOMETRY.md);
  ``index`` fields are 1-based OCCT topological indices kept for debugging.
* ``confidence`` is 1.0 only for values read directly from exact analytic
  geometry; heuristic recognitions and anything derived from a mesh are lower.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import Field

from shared_types import (
    Confidence,
    Diagnostic,
    Representation,
    SourceFormat,
    StrictModel,
    Vec3,
)

SCHEMA_VERSION = "0.1.0"

__all__ = [
    "SCHEMA_VERSION",
    "CadMetadata",
    "GeometryIR",
    "Axis",
    "BoundingBox",
    "MassProperties",
    "PrincipalAxis",
    "SymmetryCandidate",
    "SourceInfo",
    "Units",
    "TopologyCounts",
    "Body",
    "BodyKind",
    "Face",
    "Edge",
    "Vertex",
    "SurfaceType",
    "CurveType",
    "Convexity",
    "Surface",
    "PlaneSurface",
    "CylinderSurface",
    "ConeSurface",
    "SphereSurface",
    "TorusSurface",
    "OtherSurface",
    "Provenance",
    "Feature",
    "FeatureType",
    "HoleFeature",
    "HoleKind",
    "Counterbore",
    "Countersink",
    "BossFeature",
    "PocketFeature",
    "SlotFeature",
    "FilletFeature",
    "ChamferFeature",
    "PatternFeature",
    "PatternType",
    "AnalysisInfo",
]


# --------------------------------------------------------------------------- primitives


class Axis(StrictModel):
    origin: Vec3
    direction: Vec3  # unit vector


class BoundingBox(StrictModel):
    """Axis-aligned bounding box in model coordinates."""

    min: Vec3
    max: Vec3
    size: Vec3


class MassProperties(StrictModel):
    volume: float | None = Field(description="mm^3; None when not a closed volume")
    surface_area: float
    centroid: Vec3 | None = Field(description="volume centroid; None when not a closed volume")


class PrincipalAxis(StrictModel):
    direction: Vec3
    moment: float = Field(description="principal moment of inertia (unit density), mm^5")


class SymmetryCandidate(StrictModel):
    """A plane the part appears to be mirror-symmetric about."""

    plane_point: Vec3
    plane_normal: Vec3
    score: Confidence = Field(description="fraction of sampled entities matched by reflection")
    method: str


class Units(StrictModel):
    length: Literal["mm"] = "mm"
    angle: Literal["deg"] = "deg"


class SourceInfo(StrictModel):
    filename: str = Field(description="sanitized original filename (display only)")
    format: SourceFormat
    sha256: str
    size_bytes: int
    file_length_units: list[str] = Field(
        default_factory=list, description="length units declared in the file (STEP); empty for STL"
    )
    kernel: str = "OCCT"
    kernel_version: str


class TopologyCounts(StrictModel):
    solids: int
    shells: int
    faces: int
    edges: int
    vertices: int
    triangles: int | None = None  # STL only


class Provenance(StrictModel):
    method: str
    exact: bool = Field(description="True if derived from exact analytic geometry")


# --------------------------------------------------------------------------- topology


class BodyKind(StrEnum):
    SOLID = "SOLID"
    SHELL = "SHELL"
    MESH = "MESH"


class Body(StrictModel):
    id: str
    kind: BodyKind
    is_closed: bool
    is_valid: bool | None = Field(description="BRepCheck result; None when not checked")
    mass_properties: MassProperties
    bounding_box: BoundingBox
    face_ids: list[str] = Field(default_factory=list)


class SurfaceType(StrEnum):
    PLANE = "PLANE"
    CYLINDER = "CYLINDER"
    CONE = "CONE"
    SPHERE = "SPHERE"
    TORUS = "TORUS"
    BSPLINE = "BSPLINE"
    BEZIER = "BEZIER"
    REVOLUTION = "REVOLUTION"
    EXTRUSION = "EXTRUSION"
    OFFSET = "OFFSET"
    OTHER = "OTHER"


class PlaneSurface(StrictModel):
    kind: Literal["PLANE"] = "PLANE"
    origin: Vec3
    normal: Vec3 = Field(description="outward normal (face orientation applied)")


class CylinderSurface(StrictModel):
    kind: Literal["CYLINDER"] = "CYLINDER"
    axis: Axis
    radius: float
    concave: bool = Field(description="True if material is outside the cylinder (hole-like)")
    angular_extent_deg: float


class ConeSurface(StrictModel):
    kind: Literal["CONE"] = "CONE"
    axis: Axis
    half_angle_deg: float
    reference_radius: float
    apex: Vec3
    concave: bool


class SphereSurface(StrictModel):
    kind: Literal["SPHERE"] = "SPHERE"
    center: Vec3
    radius: float
    concave: bool


class TorusSurface(StrictModel):
    kind: Literal["TORUS"] = "TORUS"
    axis: Axis
    major_radius: float
    minor_radius: float


class OtherSurface(StrictModel):
    kind: Literal["OTHER"] = "OTHER"
    surface_type: SurfaceType


Surface = Annotated[
    Union[PlaneSurface, CylinderSurface, ConeSurface, SphereSurface, TorusSurface, OtherSurface],
    Field(discriminator="kind"),
]


class Face(StrictModel):
    id: str
    index: int
    body_id: str
    surface_type: SurfaceType
    surface: Surface
    area: float
    centroid: Vec3
    edge_ids: list[str]
    adjacent_face_ids: list[str]


class CurveType(StrEnum):
    LINE = "LINE"
    CIRCLE = "CIRCLE"
    ELLIPSE = "ELLIPSE"
    HYPERBOLA = "HYPERBOLA"
    PARABOLA = "PARABOLA"
    BEZIER = "BEZIER"
    BSPLINE = "BSPLINE"
    OFFSET = "OFFSET"
    OTHER = "OTHER"


class Convexity(StrEnum):
    CONVEX = "CONVEX"
    CONCAVE = "CONCAVE"
    TANGENT = "TANGENT"
    BOUNDARY = "BOUNDARY"  # used by fewer than two faces (open shell / seam)
    SEAM = "SEAM"  # same face on both sides (periodic surface seam)
    UNKNOWN = "UNKNOWN"


class Edge(StrictModel):
    id: str
    index: int
    curve_type: CurveType
    length: float
    start: Vec3
    end: Vec3
    vertex_ids: list[str]
    face_ids: list[str]
    convexity: Convexity
    circle_center: Vec3 | None = None
    circle_radius: float | None = None
    circle_axis: Vec3 | None = None


class Vertex(StrictModel):
    id: str
    index: int
    point: Vec3


# --------------------------------------------------------------------------- features


class FeatureType(StrEnum):
    HOLE = "HOLE"
    BOSS = "BOSS"
    POCKET = "POCKET"
    SLOT = "SLOT"
    FILLET = "FILLET"
    CHAMFER = "CHAMFER"
    PATTERN = "PATTERN"


class _FeatureBase(StrictModel):
    id: str
    confidence: Confidence
    face_ids: list[str]
    edge_ids: list[str] = Field(default_factory=list)
    provenance: Provenance
    notes: list[str] = Field(default_factory=list)


class HoleKind(StrEnum):
    SIMPLE = "SIMPLE"
    COUNTERBORE = "COUNTERBORE"
    COUNTERSINK = "COUNTERSINK"


class Counterbore(StrictModel):
    diameter: float
    depth: float


class Countersink(StrictModel):
    diameter: float = Field(description="diameter at the surface")
    angle_deg: float = Field(description="included angle")


class HoleFeature(_FeatureBase):
    type: Literal[FeatureType.HOLE] = FeatureType.HOLE
    kind: HoleKind
    diameter: float
    axis: Axis = Field(description="origin = centre of the entry (open) end; direction points into material")
    depth: float = Field(description="axial length of the main bore (for THRU = material thickness along axis)")
    through: bool
    counterbore: Counterbore | None = None
    countersink: Countersink | None = None


class BossFeature(_FeatureBase):
    type: Literal[FeatureType.BOSS] = FeatureType.BOSS
    diameter: float
    axis: Axis = Field(description="origin = centre of the base end, direction toward the free end")
    height: float


class PocketFeature(_FeatureBase):
    type: Literal[FeatureType.POCKET] = FeatureType.POCKET
    floor_face_id: str
    floor_normal: Vec3
    depth: float
    length: float = Field(description="extent of the floor along its principal (longest) direction")
    width: float = Field(description="extent of the floor perpendicular to length")
    length_direction: Vec3
    center: Vec3 = Field(description="centre of the floor bounding rectangle")
    corner_radius: float | None = None


class SlotFeature(_FeatureBase):
    type: Literal[FeatureType.SLOT] = FeatureType.SLOT
    width: float
    length: float = Field(description="overall length including rounded ends")
    center_distance: float = Field(description="distance between end-arc centres")
    depth: float | None
    through: bool
    length_direction: Vec3
    depth_direction: Vec3 = Field(description="points from the opening into the material")
    center: Vec3


class FilletFeature(_FeatureBase):
    type: Literal[FeatureType.FILLET] = FeatureType.FILLET
    radius: float
    concave: bool = Field(description="True = fillet (adds material in an inside corner); False = round")


class ChamferFeature(_FeatureBase):
    type: Literal[FeatureType.CHAMFER] = FeatureType.CHAMFER
    distance_1: float = Field(description="leg length measured on the first adjacent face")
    distance_2: float = Field(description="leg length measured on the second adjacent face")
    angle_deg: float = Field(description="angle between chamfer face and the first adjacent face")
    adjacent_face_ids: list[str]


class PatternType(StrEnum):
    CIRCULAR = "CIRCULAR"
    LINEAR = "LINEAR"
    RECTANGULAR = "RECTANGULAR"


class PatternFeature(_FeatureBase):
    type: Literal[FeatureType.PATTERN] = FeatureType.PATTERN
    pattern_type: PatternType
    member_feature_ids: list[str]
    member_type: FeatureType
    count: int
    # circular
    center: Vec3 | None = None
    axis_direction: Vec3 | None = None
    pitch_circle_diameter: float | None = None
    angular_step_deg: float | None = None
    # linear / rectangular
    directions: list[Vec3] = Field(default_factory=list)
    pitches: list[float] = Field(default_factory=list)
    counts: list[int] = Field(default_factory=list)


Feature = Annotated[
    Union[
        HoleFeature,
        BossFeature,
        PocketFeature,
        SlotFeature,
        FilletFeature,
        ChamferFeature,
        PatternFeature,
    ],
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- document


class AnalysisInfo(StrictModel):
    duration_s: float
    linear_tolerance_mm: float
    angular_tolerance_deg: float
    recognizers: list[str]
    not_recognized: list[str] = Field(
        default_factory=list, description="feature classes this analysis could not look for"
    )


class CadMetadata(StrictModel):
    """Product data read from the CAD file (STEP PRODUCT / version / MATERIAL_DESIGNATION / user-defined
    attributes). Every value names its origin in ``sources``; nothing here is guessed."""

    name: str | None = None
    part_number: str | None = None
    description: str | None = None
    revision: str | None = None
    material: str | None = None
    mass_g: float | None = Field(default=None, description="mass stated in the file (not computed)")
    assembly: bool = False
    attributes: dict[str, str] = Field(default_factory=dict, description="all user-defined attributes found")
    sources: dict[str, str] = Field(default_factory=dict, description="field -> STEP entity it was read from")

    @property
    def empty(self) -> bool:
        return not any((self.name, self.part_number, self.revision, self.material, self.mass_g))


class GeometryIR(StrictModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    source: SourceInfo
    cad_metadata: CadMetadata = Field(default_factory=CadMetadata)
    representation: Representation
    units: Units = Units()
    bounding_box: BoundingBox
    mass_properties: MassProperties
    principal_axes: list[PrincipalAxis]
    symmetry_candidates: list[SymmetryCandidate]
    topology: TopologyCounts
    bodies: list[Body]
    faces: list[Face]
    edges: list[Edge]
    vertices: list[Vertex]
    features: list[Feature]
    diagnostics: list[Diagnostic]
    analysis: AnalysisInfo

    def feature(self, feature_id: str) -> Feature:
        for f in self.features:
            if f.id == feature_id:
                return f
        raise KeyError(feature_id)

    def features_of(self, ftype: FeatureType) -> list[Feature]:
        return [f for f in self.features if f.type == ftype]
