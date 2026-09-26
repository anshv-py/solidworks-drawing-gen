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
5. primary rule set (rules/drawing_rules.yaml, ``view_selection=RULES``, the default):
   - functional roles are inferred (``roles.py``) and the user's overrides applied
   - RULES 1.1: the smallest subset of the projected views that still shows every dimension and every
     face annotation (one view + a THICKNESS note for a flat part whose only other dimension is its
     thickness)
   - RULES 1.2: the pictorial view is added only when an isometric trigger fires
   - RULES 1.3-1.6: section / auxiliary / break triggers are recorded (detail triggers need the scale
     and are added by the pipeline)
   - the default general tolerance and surface finish, and the role treatments (fits, GD&T, finish)
     are applied with ``default_gdt`` (all labelled source=DEFAULT)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from drawing_schema import (
    AuxiliaryView,
    ViewFrame,
    DimensionSelection,
    EngineeringField,
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
from drawing_schema.roles import ViewTrigger, ViewTriggerKind
from drawing_schema.settings import DrawingSettings, ViewSelection
from geometry_schema import FeatureType, GeometryIR
from shared_types import InfoSource

from drawing_planner.candidates import generate_candidates
from drawing_planner.gdt_defaults import default_gdt
from drawing_planner.materials import density, format_mass
from drawing_planner.pmi_validation import validate_pmi
from drawing_planner.roles import PartFamily, infer_roles, main_turned_boss
from drawing_planner.rule_set import load_rules
from drawing_planner.sections import hidden_in_section, plan_auxiliary_views, plan_break, plan_sections
from drawing_planner.threads import default_threads
from drawing_planner.view_rules import auxiliary_triggers, break_triggers, isometric_triggers, section_triggers

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


def _apply_cad_metadata(ir: GeometryIR, tb: TitleBlock, engineering, settings: DrawingSettings):
    """Title-block fields the user left empty, from the CAD file's product data (never overriding the
    user). The weight is the file's stated mass, else the exact volume x the nominal density of the stated
    material (EX 1 item 12), marked CALC."""
    meta = ir.cad_metadata
    src = meta.sources
    applied: list[str] = []
    patch: dict = {}
    if meta.name and tb.title is None:
        patch["title"] = meta.name[:60]
        applied.append(f"title '{meta.name}' ({src.get('name', 'CAD')})")
    if meta.part_number and not (tb.part_number or tb.drawing_number):
        patch["part_number"] = meta.part_number[:40]
        applied.append(f"part number {meta.part_number} ({src.get('part_number', 'CAD')})")
    if meta.revision and not tb.revision and not settings.manufacturing.revisions:
        patch["revision"] = meta.revision[:4]
        applied.append(f"revision {meta.revision} ({src.get('revision', 'CAD')})")
    if meta.material and engineering.material.status != "SPECIFIED":
        engineering = engineering.model_copy(update={"material": EngineeringField(
            status="SPECIFIED", value=meta.material, source=InfoSource.CAD_MODEL)})
        applied.append(f"material {meta.material} ({src.get('material', 'CAD')})")
    if not tb.weight:
        if meta.mass_g:
            patch["weight"] = format_mass(meta.mass_g)
            applied.append(f"weight {patch['weight']} ({src.get('mass', 'CAD')})")
        elif engineering.material.status == "SPECIFIED" and ir.mass_properties.volume:
            rho = density(engineering.material.value)
            if rho is not None:
                grams = ir.mass_properties.volume / 1000.0 * rho[0]
                patch["weight"] = f"{format_mass(grams)} (CALC.)"
                applied.append(f"weight {format_mass(grams)} calculated: CAD volume "
                               f"{ir.mass_properties.volume / 1000:.2f} cm³ x {rho[0]:g} g/cm³ ({rho[1]})")
    if patch:
        tb = TitleBlock(**{**tb.model_dump(), **patch})
    return tb, engineering, applied


def _face_targets(m, gdt) -> set[str]:
    """Faces that carry an annotation: they must stay edge-on in some selected view."""
    targets = [d.target for d in m.datums] + [f.target for f in m.frames] + [x.target for x in m.surface_finish_marks]
    if gdt is not None:
        targets += [d.target for d in gdt.datums] + [f.target for f in gdt.frames] + [
            x.target for x in gdt.finish_marks] + [n.target for n in gdt.feature_notes]
    return {t.face_id for t in targets if t.face_id}


def _thickness_only(missing: list[DimensionCandidate], f: Frame, ir: GeometryIR, max_ratio: float) -> bool:
    """RULES 1.1: a flat part (gasket, shim, plate) whose only dimension a single view cannot show is its
    overall thickness along the line of sight (it becomes a note)."""
    if len(missing) != 1 or missing[0].role != CandidateRole.OVERALL or missing[0].direction is None:
        return False
    if abs(dot(missing[0].direction, f.eye)) <= PARALLEL:
        return False
    others = sorted(ir.bounding_box.size)[1:] if missing[0].value <= min(ir.bounding_box.size) + 1e-6 else []
    return bool(others) and missing[0].value <= max_ratio * others[0] + 1e-9


def plan_baseline(
    ir: GeometryIR, settings: DrawingSettings, *, filename: str | None = None
) -> PlanResult:
    dp = settings.dimensions.decimal_places
    rules = load_rules()
    roles = infer_roles(ir, rules, settings.feature_roles, settings.manufacturing.threads)
    rules_mode = settings.view_selection == ViewSelection.RULES
    threads = list(settings.manufacturing.threads)
    if rules_mode and settings.default_gdt:  # tapped holes: derived callouts (TAPPED_HOLE treatment)
        threads += default_threads(ir, roles, rules, threads)
    candidates = generate_candidates(ir, dp, settings.dimensions.trailing_zeros, threads)
    hole_ids = {f.id for f in ir.features if f.type == FeatureType.HOLE}
    prefs = settings.dimensions.model_dump()
    enabled = [c for c in candidates if prefs.get(_category(c, hole_ids), True)]
    if not settings.annotations.hole_callouts:
        enabled = [c for c in enabled if c.kind != CandidateKind.HOLE_CALLOUT]
    kept, dropped = remove_redundant(enabled)


    pool = list(settings.projected_views)
    primary_ortho = settings.primary_view not in PICTORIAL
    if primary_ortho and settings.primary_view not in pool:
        pool.insert(0, settings.primary_view)
    frame_kind = settings.view_frame
    if rules_mode and roles.family == PartFamily.SHAFT:
        # EX 3: a shaft is drawn with its axis horizontal in the front view (keep the user's frame if it does)
        boss, _ = main_turned_boss(ir)
        frame_kind = next(f for f in [settings.view_frame, *ViewFrame]
                          if abs(abs(dot(view_frame(ViewOrientation.FRONT, f).x, boss.axis.direction)) - 1) < 1e-6)
    frames = {o: view_frame(o, frame_kind) for o in pool}

    def assign(views: list[ViewOrientation], skip: set[str], forbid: dict | None = None):
        """``forbid``: candidate id -> views that must not carry it (a section hiding its feature)."""
        order = [o for o in VIEW_PREFERENCE if o in views]
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
            if c.id in skip:
                continue
            options = [o for o in order if _compatible(c, frames[o]) and o not in (forbid or {}).get(c.id, ())]
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
        return selections, uncertainties

    manufacturing, engineering = settings.manufacturing, settings.engineering_information
    manufacturing = manufacturing.model_copy(update={"threads": threads})
    user_gdt = bool(manufacturing.datums or manufacturing.frames)
    apply_defaults = settings.default_gdt and not user_gdt
    user_tolerances = {t.candidate_id for t in manufacturing.tolerances}

    def gdt_for(views: list[ViewOrientation], selections: list[DimensionSelection]):
        if not apply_defaults:
            return None
        placed_ids = {x.candidate_id for x in selections}
        return default_gdt(ir, [c for c in candidates if c.id in placed_ids], [frames[o] for o in views],
                           roles if rules_mode else None, rules if rules_mode else None, user_tolerances)

    views = [o for o in VIEW_PREFERENCE if o in pool] + [o for o in pool if o not in VIEW_PREFERENCE]
    selections, uncertainties = assign(views, set())
    thickness = None
    if rules_mode and rules.views.minimal_orthographic and len(views) > 1:
        full = gdt_for(views, selections)
        normals = [f.surface.normal for f in ir.faces if f.id in _face_targets(manufacturing, full)
                   and f.surface_type.value == "PLANE"]
        placeable = [c for c in kept if any(_compatible(c, frames[o]) for o in views)]
        found = None
        for size in range(1, len(views)):
            for subset in combinations(views, size):
                if size >= 2 and ViewOrientation.FRONT in views and ViewOrientation.FRONT not in subset:
                    continue  # projected views are aligned to FRONT
                if not all(any(abs(dot(n, frames[o].eye)) < 1e-6 for o in subset) for n in normals):
                    continue
                missing = [c for c in placeable if not any(_compatible(c, frames[o]) for o in subset)]
                if not missing:
                    found = (list(subset), None)
                elif size == 1 and rules.views.single_view_thickness_note and _thickness_only(
                        missing, frames[subset[0]], ir, rules.views.single_view_max_thickness_ratio):
                    found = (list(subset), missing[0])
                if found:
                    break
            if found:
                break
        if found:
            views, thickness = found
            selections, uncertainties = assign(views, {thickness.id} if thickness else set())

    # RULES 1.3: a full section in place of a view (it may need a view that shows the cutting plane)
    sections: list = []
    sec_triggers = section_triggers(ir, rules) if rules_mode else []
    if sec_triggers:
        sections, extra, sec_triggers = plan_sections(ir, views, pool, frames, sec_triggers)
        forbid: dict = {}
        for sec in sections:
            hidden = hidden_in_section(ir, sec, frames[sec.replaces])
            for c in kept:
                if c.feature_ids and set(c.feature_ids) <= hidden:
                    forbid.setdefault(c.id, set()).add(sec.replaces)
        # a dimension only the section could carry: add the pool view that shows it
        for c in kept:
            shown = [o for o in views + extra if _compatible(c, frames[o]) and o not in forbid.get(c.id, ())]
            if c.id in forbid and not shown:
                more = next((o for o in VIEW_PREFERENCE if o in pool and o not in views + extra
                             and _compatible(c, frames[o])), None)
                if more is not None:
                    extra.append(more)
        if extra or forbid:
            views = [o for o in VIEW_PREFERENCE if o in views or o in extra]
            if extra:
                thickness = None  # the added view shows the thickness
            selections, uncertainties = assign(views, {thickness.id} if thickness else set(), forbid)

    # RULES 1.5: features on angled faces get an auxiliary view along their axis; the dimensions no
    # principal view shows true size go there
    aux_views: list[AuxiliaryView] = []
    aux_triggers = auxiliary_triggers(ir, rules) if rules_mode else []
    if aux_triggers:
        aux_views, aux_frames = plan_auxiliary_views(ir, views, frames, aux_triggers)
        placed_ids = {x.candidate_id for x in selections}
        for c in kept:
            if c.id in placed_ids or (thickness is not None and c.id == thickness.id):
                continue
            for av in aux_views:
                if set(c.feature_ids) & set(av.covers) and _compatible(c, aux_frames[av.id]):
                    selections.append(DimensionSelection(candidate_id=c.id, view_id=av.id))
                    uncertainties = [u for u in uncertainties if not u.message.startswith(f"{c.id} ")]
                    break
        covered = {fid for av in aux_views for fid in av.covers}
        aux_triggers = [t.model_copy(update={"satisfied": True}) if set(t.feature_ids) <= covered else t
                        for t in aux_triggers]

    for c in dropped:
        uncertainties.append(
            PlanUncertainty(message=f"{c.id} ({c.text}) omitted: redundant with a higher-priority dimension",
                            related_ids=c.feature_ids)
        )
    if ir.representation != "EXACT_BREP":
        uncertainties.append(PlanUncertainty(message="tessellated source: dimensions are approximate"))

    triggers: list[ViewTrigger] = []
    breaks: list = []
    rule_notes: list[str] = []
    pictorial = settings.primary_view if settings.primary_view in PICTORIAL else ViewOrientation.ISOMETRIC
    if rules_mode:
        iso = isometric_triggers(ir, rules, settings.general_notes.process)
        show_pictorial = bool(iso)
        triggers += [t.model_copy(update={"satisfied": True}) for t in iso]
        brk_triggers = break_triggers(ir, rules)
        if roles.family == PartFamily.SHAFT:
            breaks, brk_triggers = plan_break(ir, brk_triggers, sections)
        triggers += sec_triggers + aux_triggers + brk_triggers
        if thickness is not None:
            rule_notes.append(f"THICKNESS {thickness.text}")
            triggers.append(ViewTrigger(kind=ViewTriggerKind.THICKNESS_NOTE, rule="RULES 1.1 (one view + note)",
                                        message=f"flat part drawn in one view; thickness {thickness.text} given "
                                                "as a note", feature_ids=list(thickness.feature_ids), satisfied=True))
    else:
        show_pictorial = not primary_ortho

    if show_pictorial:
        primary = ViewSpec(id="V-PRIMARY", orientation=pictorial, dimensioned=False)
        projected = list(views) if rules_mode else list(settings.projected_views)
    else:
        main = settings.primary_view if primary_ortho and settings.primary_view in views else (
            ViewOrientation.FRONT if ViewOrientation.FRONT in views else views[0])
        primary = ViewSpec(id=view_id(main), orientation=main, dimensioned=True,
                           display_style=settings.orthographic_display_style)
        projected = [o for o in (views if rules_mode else settings.projected_views) if o != main]

    rationale = ("deterministic baseline planner v1 (no LLM): GeometryIR candidates, chain-redundancy "
                 "removal, true-size view assignment")
    if rules_mode:
        rationale += (f"; rule set {rules.label}: {len(views)} orthographic view(s) (RULES 1.1), "
                      f"{'isometric (RULES 1.2 trigger)' if show_pictorial else 'no isometric (no RULES 1.2 trigger)'}")
    if settings.default_gdt:
        general = rules.defaults.general_tolerance
        if (engineering.general_tolerance.status != "SPECIFIED"
                and engineering.linear_tolerance.status != "SPECIFIED"):
            engineering = engineering.model_copy(update={"general_tolerance": EngineeringField(
                status="SPECIFIED", value=general, source=InfoSource.DEFAULT)})
        if rules_mode and engineering.surface_finish.status != "SPECIFIED":
            engineering = engineering.model_copy(update={"surface_finish": EngineeringField(
                status="SPECIFIED", value=f"Ra {rules.defaults.default_surface_finish_ra:g}", source=InfoSource.DEFAULT)})
    gdt = gdt_for(views, selections)
    if gdt is not None and not gdt.empty:
        manufacturing = manufacturing.model_copy(update={
            "datums": gdt.datums, "frames": gdt.frames,
            "basic_dimensions": list(dict.fromkeys(manufacturing.basic_dimensions + gdt.basic_dimensions)),
            "tolerances": manufacturing.tolerances + gdt.tolerances,
            "surface_finish_marks": manufacturing.surface_finish_marks + [
                m for m in gdt.finish_marks
                if all(u.target != m.target for u in manufacturing.surface_finish_marks)],
            "feature_notes": manufacturing.feature_notes + gdt.feature_notes,
        })
        uncertainties += [PlanUncertainty(message=u) for u in gdt.uncertainties]
        rationale += ("; default datums and GD&T (" + engineering.general_tolerance.value + "): "
                      if engineering.general_tolerance.status == "SPECIFIED" else "; default datums and GD&T: ")
        rationale += "; ".join(gdt.rationale)
    if sections:
        # view designations never reuse a datum letter on the same sheet
        free = [c for c in "ABCDEFGHJKLMNPRSTUVWXYZ" if c not in {d.letter for d in manufacturing.datums}]
        sections = [s.model_copy(update={"label": free[k]}) for k, s in enumerate(sections)]
    if aux_views:
        free = [c for c in "ABCDEFGHJKLMNPRSTUVWXYZ"
                if c not in {d.letter for d in manufacturing.datums} | {s.label for s in sections}]
        relabel = {a.id: free[k] for k, a in enumerate(aux_views)}
        aux_views = [a.model_copy(update={"label": relabel[a.id]}) for a in aux_views]
    tb = settings.title_block
    cad_applied: list[str] = []
    if settings.use_cad_metadata:
        tb, engineering, cad_applied = _apply_cad_metadata(ir, tb, engineering, settings)
    if tb.title is None and filename:
        tb = TitleBlock(**{**tb.model_dump(), "title": filename.rsplit(".", 1)[0]})
    plan = DrawingPlan(
        geometry=GeometryReference(source_sha256=ir.source.sha256, geometry_schema_version=ir.schema_version),
        drawing_kind=settings.drawing_kind,
        drawing_standard=settings.drawing_standard,
        projection_method=settings.projection_method,
        sheet=settings.sheet,
        view_frame=frame_kind,
        orthographic_display_style=settings.orthographic_display_style,
        primary_view=primary,
        projected_views=projected,
        dimensions=settings.dimensions,
        dimension_selections=selections,
        annotations=settings.annotations,
        engineering_information=engineering,
        title_block=tb,
        manufacturing=manufacturing,
        general_notes=settings.general_notes,
        pictorial_style=settings.pictorial_style,
        uncertainties=uncertainties,
        rationale=rationale[:2000],
        rule_set=rules.label if rules_mode else None,
        sections=sections,
        auxiliary_views=aux_views,
        breaks=breaks,
        feature_roles=roles.assignments if rules_mode else [],
        view_triggers=triggers,
        rule_notes=rule_notes,
        cad_metadata_applied=cad_applied,
    )
    result = PlanResult(plan=plan, candidates=candidates)
    placed = {s.candidate_id for s in plan.dimension_selections}
    result.errors = roles.errors + validate_pmi(ir, manufacturing, [c for c in candidates if c.id in placed])
    return result
