"""Deterministic baseline planner: GeometryIR + DrawingSettings -> DrawingPlan (no LLM).

Rules (in order):
1. candidates from GeometryIR (``candidates.generate_candidates``)
2. user dimension preferences filter candidate categories
3. redundancy: linear dimensions are intervals on a model axis; a union-find over the
   interval end coordinates drops any dimension that would close a chain (or duplicate an
   interval) - higher-priority candidates win
4. view assignment: each surviving candidate goes to the first selected orthographic view
   that shows it true size, preferring the view that shows the owning feature's circle /
   floor face from its open side
"""

from __future__ import annotations

from dataclasses import dataclass, field

from drawing_schema import (
    DimensionSelection,
    DrawingPlan,
    GeometryReference,
    PlanUncertainty,
    TitleBlock,
    ViewOrientation,
    ViewSpec,
    PICTORIAL,
)
from drawing_schema.candidates import CandidateKind, CandidateRole, DimensionCandidate, ViewRule
from drawing_schema.frames import Frame, dot, view_frame
from drawing_schema.settings import DrawingSettings
from geometry_schema import FeatureType, GeometryIR

from drawing_planner.candidates import generate_candidates
from drawing_planner.pmi_validation import validate_pmi

VIEW_PREFERENCE = [
    ViewOrientation.FRONT, ViewOrientation.TOP, ViewOrientation.RIGHT,
    ViewOrientation.LEFT, ViewOrientation.BOTTOM, ViewOrientation.BACK,
]
PARALLEL = 1.0 - 1e-6
PERPENDICULAR = 1e-6


def view_id(o: ViewOrientation) -> str:
    return f"V-{o.value}"


@dataclass
class PlanResult:
    plan: DrawingPlan
    candidates: list[DimensionCandidate]  # all candidates (selected ones are referenced by the plan)
    errors: list[str] = field(default_factory=list)  # invalid user annotations (drawing must not be made)


def _category(c: DimensionCandidate, hole_ids: set[str]) -> str:
    if c.role == CandidateRole.OVERALL:
        return "overall"
    if c.kind == CandidateKind.HOLE_CALLOUT or c.kind == CandidateKind.PCD or c.role == CandidateRole.PITCH:
        return "holes"
    if c.role == CandidateRole.LOCATION:
        return "holes" if set(c.feature_ids) & hole_ids else "feature"
    if c.kind == CandidateKind.DIAMETER:
        return "diameters"
    if c.kind == CandidateKind.RADIUS:
        return "radii"
    if c.role == CandidateRole.DEPTH:
        return "depths"
    if c.kind == CandidateKind.CHAMFER:
        return "angles"
    return "feature"


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.parent[ra] = rb
        return True


def remove_redundant(cands: list[DimensionCandidate]) -> tuple[list[DimensionCandidate], list[DimensionCandidate]]:
    kept, dropped = [], []
    uf = _UnionFind()
    seen_other: set[tuple] = set()
    for c in sorted(cands, key=lambda c: (c.priority, c.id)):
        if c.kind == CandidateKind.LINEAR and c.direction is not None:
            d = tuple(round(x, 6) for x in c.direction)
            d = d if next(x for x in d if abs(x) > 1e-9) > 0 else tuple(-x for x in d)
            a = round(dot(c.p1, d), 4)
            b = round(dot(c.p2, d), 4)
            # Nodes are (axis, coordinate, kind). Face/edge extremes at one coordinate are the same
            # plane and link chains; feature centres only link with other centres (aligned holes
            # are dimensioned once) - never with a face that merely shares the coordinate.
            ka, kb = ("C" if k.startswith("CENTER") else "F" for k in c.anchors)
            if uf.union((d, a, ka), (d, b, kb)):
                kept.append(c)
            else:
                dropped.append(c)
        else:
            key = (c.kind, round(c.value, 4), tuple(round(x, 4) for x in (c.center or ())), c.text)
            if key in seen_other:
                dropped.append(c)
            else:
                seen_other.add(key)
                kept.append(c)
    return kept, dropped


def _compatible(c: DimensionCandidate, f: Frame) -> bool:
    if c.view_rule == ViewRule.IN_PLANE:
        return abs(dot(c.direction, f.eye)) < PERPENDICULAR
    if c.view_rule == ViewRule.ALONG_AXIS:
        return abs(dot(c.axis, f.eye)) > PARALLEL
    return abs(dot(c.axis, f.eye)) < PERPENDICULAR  # ACROSS_AXIS


def _entry_score(c: DimensionCandidate, f: Frame, ir: GeometryIR) -> int:
    """0 if the view looks at the feature's open side, 1 otherwise."""
    if c.kind != CandidateKind.HOLE_CALLOUT:
        return 0
    feats = {x.id: x for x in ir.features}
    h = next((feats[i] for i in c.feature_ids if i in feats and feats[i].type == FeatureType.HOLE), None)
    if h is None or h.through:
        return 0
    return 0 if dot(f.eye, tuple(-x for x in h.axis.direction)) > 0 else 1


def plan_baseline(
    ir: GeometryIR, settings: DrawingSettings, *, filename: str | None = None
) -> PlanResult:
    dp = settings.dimensions.decimal_places
    candidates = generate_candidates(ir, dp, settings.dimensions.trailing_zeros, settings.manufacturing.threads)
    hole_ids = {f.id for f in ir.features if f.type == FeatureType.HOLE}
    prefs = settings.dimensions.model_dump()
    enabled = [c for c in candidates if prefs.get(_category(c, hole_ids), True)]
    if not settings.annotations.hole_callouts:
        enabled = [c for c in enabled if c.kind != CandidateKind.HOLE_CALLOUT]
    kept, dropped = remove_redundant(enabled)

    ortho = list(settings.projected_views)
    primary_ortho = settings.primary_view not in PICTORIAL
    if primary_ortho and settings.primary_view not in ortho:
        ortho.insert(0, settings.primary_view)
    frames = {o: view_frame(o, settings.view_frame) for o in ortho}
    order = [o for o in VIEW_PREFERENCE if o in frames]

    feature_view: dict[str, ViewOrientation] = {}
    # pockets / slots: the view looking into their opening shows their outline true size
    for feat in ir.features:
        normal = getattr(feat, "floor_normal", None) or (
            tuple(-x for x in feat.depth_direction) if feat.type == FeatureType.SLOT else None
        )
        if normal is None:
            continue
        facing = [o for o in order if dot(frames[o].eye, normal) > 1 - 1e-6]
        if facing:
            feature_view[feat.id] = facing[0]
    selections: list[DimensionSelection] = []
    uncertainties: list[PlanUncertainty] = []
    # callouts / radii / PCD first so their features' views are known for the linear dims
    ordered = sorted(kept, key=lambda c: (0 if c.view_rule == ViewRule.ALONG_AXIS else 1, c.priority, c.id))
    for c in ordered:
        options = [o for o in order if _compatible(c, frames[o])]
        if not options:
            uncertainties.append(
                PlanUncertainty(
                    message=f"{c.id} ({c.text}) is not shown true size in any selected view; not dimensioned",
                    related_ids=c.feature_ids,
                )
            )
            continue
        preferred = [feature_view[f] for f in c.feature_ids if f in feature_view and feature_view[f] in options]
        if preferred and c.view_rule == ViewRule.IN_PLANE and c.role in (
            CandidateRole.LOCATION, CandidateRole.PITCH, CandidateRole.SIZE
        ):
            choice = preferred[0]
        else:
            choice = min(options, key=lambda o: (_entry_score(c, frames[o], ir), order.index(o)))
        if c.view_rule == ViewRule.ALONG_AXIS:
            for fid in c.feature_ids:
                feature_view.setdefault(fid, choice)
        selections.append(DimensionSelection(candidate_id=c.id, view_id=view_id(choice)))

    for c in dropped:
        uncertainties.append(
            PlanUncertainty(message=f"{c.id} ({c.text}) omitted: redundant with a higher-priority dimension",
                            related_ids=c.feature_ids)
        )
    if ir.representation != "EXACT_BREP":
        uncertainties.append(PlanUncertainty(message="tessellated source: dimensions are approximate"))

    if primary_ortho:
        primary = ViewSpec(id=view_id(settings.primary_view), orientation=settings.primary_view, dimensioned=True,
                           display_style=settings.orthographic_display_style)
        projected = [o for o in settings.projected_views if o != settings.primary_view]
    else:
        primary = ViewSpec(id="V-PRIMARY", orientation=settings.primary_view, dimensioned=False)
        projected = list(settings.projected_views)
    tb = settings.title_block
    if tb.title is None and filename:
        tb = TitleBlock(**{**tb.model_dump(), "title": filename.rsplit(".", 1)[0]})
    plan = DrawingPlan(
        geometry=GeometryReference(source_sha256=ir.source.sha256, geometry_schema_version=ir.schema_version),
        drawing_kind=settings.drawing_kind,
        drawing_standard=settings.drawing_standard,
        projection_method=settings.projection_method,
        sheet=settings.sheet,
        view_frame=settings.view_frame,
        orthographic_display_style=settings.orthographic_display_style,
        primary_view=primary,
        projected_views=projected,
        dimensions=settings.dimensions,
        dimension_selections=selections,
        annotations=settings.annotations,
        engineering_information=settings.engineering_information,
        title_block=tb,
        manufacturing=settings.manufacturing,
        pictorial_style=settings.pictorial_style,
        uncertainties=uncertainties,
        rationale="deterministic baseline planner v1 (no LLM): GeometryIR candidates, chain-redundancy "
        "removal, true-size view assignment",
    )
    result = PlanResult(plan=plan, candidates=candidates)
    placed = {s.candidate_id for s in plan.dimension_selections}
    result.errors = validate_pmi(ir, settings.manufacturing, [c for c in candidates if c.id in placed])
    return result
