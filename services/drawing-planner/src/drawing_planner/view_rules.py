"""View rules of the primary rule set (RULES 1.2 - 1.6): which extra views a part needs.

Detected here and recorded on the plan as ``ViewTrigger``s. The isometric is added by the planner; section,
detail, auxiliary and break views are reported (``satisfied=False``) until the phases that draw them
(docs/ROADMAP.md). The minimum-orthographic-view search (RULES 1.1) lives in ``baseline.py``.
"""

from __future__ import annotations

import math

from drawing_schema.pmi import ManufacturingProcess
from drawing_schema.roles import ViewTrigger, ViewTriggerKind as K
from geometry_schema import FeatureType, GeometryIR, SurfaceType

from drawing_planner.rule_set import RuleSet

_EPS = 1e-6


def _principal(v) -> bool:
    return max(abs(x) for x in v) > 1 - _EPS


def nonorthogonal_faces(ir: GeometryIR) -> list[str]:
    """Faces whose orientation is not along X/Y/Z (angled planes, tilted or free-form surfaces).
    Fillet and chamfer faces are edge treatments, not spatial complexity, and are excluded."""
    treated = {fid for f in ir.features if f.type in (FeatureType.FILLET, FeatureType.CHAMFER) for fid in f.face_ids}
    out = []
    for face in ir.faces:
        if face.id in treated:
            continue
        s = face.surface
        if face.surface_type == SurfaceType.PLANE:
            if not _principal(s.normal):
                out.append(face.id)
        elif face.surface_type in (SurfaceType.CYLINDER, SurfaceType.CONE, SurfaceType.TORUS):
            if not _principal(s.axis.direction):
                out.append(face.id)
        elif face.surface_type != SurfaceType.SPHERE:
            out.append(face.id)  # B-spline, revolution, extrusion ...: free-form
    return out


def isometric_triggers(ir: GeometryIR, rules: RuleSet, process: ManufacturingProcess) -> list[ViewTrigger]:
    t = rules.views.isometric_triggers
    out = []
    faces = nonorthogonal_faces(ir)
    if len(faces) > t.nonorthogonal_face_count_gt:
        out.append(ViewTrigger(kind=K.ISOMETRIC, rule="RULES 1.2 (non-obvious spatial relationship)",
                               message=f"{len(faces)} faces are not square to the principal planes",
                               feature_ids=faces[:20], satisfied=False))
    if process in t.processes:
        out.append(ViewTrigger(kind=K.ISOMETRIC, rule="RULES 1.2 (casting / forging / moulding)",
                               message=f"process {process.value}", satisfied=False))
    if len(ir.bodies) > t.assembly_bodies_gt:
        out.append(ViewTrigger(kind=K.ISOMETRIC, rule="RULES 1.2 (assembly)",
                               message=f"{len(ir.bodies)} bodies", satisfied=False))
    return out


def section_triggers(ir: GeometryIR, rules: RuleSet) -> list[ViewTrigger]:
    t = rules.views.section_triggers
    holes = [f for f in ir.features if f.type == FeatureType.HOLE]
    out = []
    for h in holes:
        if not h.through and h.depth > t.blind_hole_depth_to_diameter_gt * h.diameter + _EPS:
            out.append(ViewTrigger(kind=K.SECTION, rule="RULES 1.3 (deep blind hole)",
                                   message=f"blind Ø{h.diameter:g} hole {h.depth:g} deep (depth/Ø "
                                           f"{h.depth / h.diameter:.1f} > {t.blind_hole_depth_to_diameter_gt:g})",
                                   feature_ids=[h.id], satisfied=False))
        elif t.counterbore_or_countersink and (h.counterbore is not None or h.countersink is not None):
            out.append(ViewTrigger(kind=K.SECTION, rule="RULES 1.3 (stepped bore)",
                                   message=f"Ø{h.diameter:g} hole with a "
                                           f"{'counterbore' if h.counterbore else 'countersink'}: full section",
                                   feature_ids=[h.id], satisfied=False))
    if t.stepped_coaxial_bores:
        for i, a in enumerate(holes):
            for b in holes[i + 1:]:
                if abs(abs(sum(x * y for x, y in zip(a.axis.direction, b.axis.direction))) - 1) > _EPS:
                    continue
                off = [a.axis.origin[k] - b.axis.origin[k] for k in range(3)]
                along = sum(o * d for o, d in zip(off, a.axis.direction))
                radial = math.sqrt(max(0.0, sum(o * o for o in off) - along * along))
                if radial < 1e-3 and abs(a.diameter - b.diameter) > 1e-3:
                    out.append(ViewTrigger(kind=K.SECTION, rule="RULES 1.3 (concentric / stepped bores)",
                                           message=f"coaxial Ø{a.diameter:g} and Ø{b.diameter:g} bores",
                                           feature_ids=[a.id, b.id], satisfied=False))
    return out


def auxiliary_triggers(ir: GeometryIR, rules: RuleSet) -> list[ViewTrigger]:
    if not rules.views.auxiliary_triggers.feature_axis_not_principal:
        return []
    out = []
    for f in ir.features:
        d = (f.axis.direction if f.type in (FeatureType.HOLE, FeatureType.BOSS)
             else getattr(f, "floor_normal", None) or getattr(f, "depth_direction", None))
        if d is not None and not _principal(d):
            out.append(ViewTrigger(kind=K.AUXILIARY, rule="RULES 1.5",
                                   message=f"{f.type.value.lower()} {f.id} lies on an angled face: "
                                           "only an auxiliary view shows it true size",
                                   feature_ids=[f.id], satisfied=False))
    return out


def break_triggers(ir: GeometryIR, rules: RuleSet) -> list[ViewTrigger]:
    size = sorted(ir.bounding_box.size, reverse=True)
    ratio = size[0] / max(size[1], _EPS)
    if ratio > rules.views.break_triggers.length_to_width_ratio_gt:
        return [ViewTrigger(kind=K.BREAK, rule="RULES 1.6",
                            message=f"long part (length/width {ratio:.1f}): a conventional break keeps the scale "
                                    "legible", satisfied=False)]
    return []


def _feature_size(f) -> float | None:
    """The smallest size that must be seen to read the feature."""
    t = f.type
    if t in (FeatureType.HOLE, FeatureType.BOSS):
        return f.diameter
    if t == FeatureType.SLOT:
        return f.width
    if t == FeatureType.POCKET:
        return min(f.width, f.length)
    if t == FeatureType.FILLET:
        return f.radius
    if t == FeatureType.CHAMFER:
        return min(f.distance_1, f.distance_2)
    return None


def detail_triggers(ir: GeometryIR, rules: RuleSet, scale: float, tight_feature_ids: set[str]) -> list[ViewTrigger]:
    """RULES 1.4 at the drawing's actual scale: features printed too small to read, and tightly
    toleranced features on a reduced drawing."""
    t = rules.views.detail_triggers
    small, tight = [], []
    for f in ir.features:
        size = _feature_size(f)
        if size is not None and size * scale < t.feature_size_on_sheet_lt_mm - _EPS:
            small.append((f.id, size))
    if scale < t.tight_tolerance_scale_lt - _EPS:
        tight = sorted(tight_feature_ids)
    out = []
    if small:
        out.append(ViewTrigger(kind=K.DETAIL, rule="RULES 1.4 (small feature)",
                               message=f"{len(small)} feature(s) print smaller than "
                                       f"{t.feature_size_on_sheet_lt_mm:g} mm at this scale (smallest "
                                       f"{min(s for _, s in small):g} mm)",
                               feature_ids=[i for i, _ in small][:20], satisfied=False))
    if tight:
        out.append(ViewTrigger(kind=K.DETAIL, rule="RULES 1.4 (tight tolerance below 1:2)",
                               message=f"{len(tight)} feature(s) toleranced tighter than "
                                       f"{t.tight_tolerance_lt_mm:g} mm on a drawing smaller than 1:2",
                               feature_ids=tight[:20], satisfied=False))
    return out


__all__ = ["auxiliary_triggers", "break_triggers", "detail_triggers", "isometric_triggers",
           "nonorthogonal_faces", "section_triggers"]
