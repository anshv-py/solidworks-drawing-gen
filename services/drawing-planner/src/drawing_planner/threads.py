"""Default thread callouts for tapped holes (primary rule set, TAPPED_HOLE treatment).

STEP files carry no threads: a tapped hole arrives as its drilled core. For every hole with the
TAPPED_HOLE role (assumed from the tap-drill size, or set by the user) that has no thread callout of the
user's, the callout is derived: ISO 261 coarse pitch, class 6H (ISO 965-1 default for internal threads),
and - owner decision 2026-09-26 - a blind thread's depth assumed as drill depth - 3 x pitch. Labelled
``source=DEFAULT``; the role stays an assumption to confirm.
"""

from __future__ import annotations

from drawing_schema.pmi import ThreadCallout
from drawing_schema.roles import FeatureRole
from geometry_schema import FeatureType, GeometryIR
from shared_types import InfoSource

from drawing_planner.roles import RoleResult
from drawing_planner.rule_set import RuleSet


def default_threads(ir: GeometryIR, roles: RoleResult, rules: RuleSet, user: list[ThreadCallout]) -> list[ThreadCallout]:
    t = rules.treatment(FeatureRole.TAPPED_HOLE)
    tap = rules.roles.inference.tapped_holes
    feats = {f.id: f for f in ir.features}
    have = {c.feature_id for c in user}
    out: list[ThreadCallout] = []
    for a in roles.assignments:
        if a.role != FeatureRole.TAPPED_HOLE or a.target.feature_id not in feats:
            continue
        f = feats[a.target.feature_id]
        holes = [feats[m] for m in f.member_feature_ids] if f.type == FeatureType.PATTERN else [f]
        for h in holes:
            if h.type != FeatureType.HOLE or h.id in have:
                continue
            m = tap.match(h.diameter) or tap.nominal(h.diameter)
            if m is None:
                continue  # no designation can be derived: compliance item 7 asks for one
            size, _, pitch = m
            depth = None
            if not h.through:
                if t.blind_thread_depth != "DRILL_DEPTH_MINUS_3P":
                    continue
                depth = round(h.depth - 3 * pitch, 3)
                if depth <= 0:
                    continue
            out.append(ThreadCallout(feature_id=h.id, designation=f"{size}x{pitch:g}-{t.thread_class or '6H'}",
                                     depth=depth, source=InfoSource.DEFAULT))
    return out


__all__ = ["default_threads"]
