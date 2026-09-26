"""Detail views (RULES 1.4): enlarged circular regions around features too small to read at the scale.

Planned after the sheet scale is known (the pipeline calls ``plan_details`` with the RULES 1.4
triggers of the final layout). Features close together share one detail. The detail scale is the
smallest drawing scale that prints the smallest feature at ``READABLE_MM``; the region radius keeps the
detail circle about ``DETAIL_DIAMETER_MM`` across on the sheet. The parent is the (non-section) view
that carries the feature's dimension, else the main orthographic view. At most ``MAX_DETAILS``.
"""

from __future__ import annotations

import math

from drawing_schema import DRAWING_SCALES, PICTORIAL, DetailView, DrawingPlan, ViewOrientation
from drawing_schema.frames import Frame, dot, view_frame
from drawing_schema.candidates import DimensionCandidate
from geometry_schema import GeometryIR

from drawing_planner.view_rules import _feature_size

READABLE_MM = 3.0  # printed size of the smallest feature in its detail
DETAIL_DIAMETER_MM = 44.0  # printed diameter of a detail circle
MAX_DETAIL_DIAMETER_MM = 90.0
MAX_DETAILS = 2
MAX_DETAIL_SCALE = 10.0
LETTERS = [c for c in "ABCDEFGHJKLMNPRSTUVWXYZ"]  # ISO: no I, O, Q


def scale_value(s: str) -> float:
    a, b = s.split(":")
    return float(a) / float(b)


def feature_point(ir: GeometryIR, fid: str, frame: Frame) -> tuple[float, float, float] | None:
    """Where the feature shows in the view: its edge points (the extreme point of each circular edge
    along the view's x, else the edge ends); the one furthest right, averaged with the feature's other
    edge points close to it (a chamfer's two circles, a fillet's two tangent lines ...)."""
    f = next((x for x in ir.features if x.id == fid), None)
    if f is None:
        return None
    faces = {x.id: x for x in ir.faces}
    edges = {e.id: e for e in ir.edges}
    eids = set(f.edge_ids) | {e for i in f.face_ids if i in faces for e in faces[i].edge_ids}
    pts = []
    for e in (edges[i] for i in sorted(eids) if i in edges):
        if e.circle_center is not None and e.circle_axis is not None and e.circle_radius:
            a = e.circle_axis
            d = [frame.x[k] - dot(frame.x, a) * a[k] for k in range(3)]
            n = math.sqrt(sum(x * x for x in d))
            if n > 1e-9:
                pts.append(tuple(e.circle_center[k] + e.circle_radius * d[k] / n for k in range(3)))
                continue
        pts += [tuple(e.start), tuple(e.end)]
    if not pts:
        return None
    best = max(pts, key=lambda p: (round(dot(p, frame.x), 6), round(dot(p, frame.y), 6)))
    size = _feature_size(f) or 1.0
    near = [p for p in pts if math.dist(p, best) <= 3 * size]
    return tuple(sum(p[k] for p in near) / len(near) for k in range(3))


def plan_details(ir: GeometryIR, plan: DrawingPlan, candidates: list[DimensionCandidate], sheet_scale: str,
                 feature_ids: list[str]) -> list[DetailView]:
    s = scale_value(sheet_scale)
    feats = {f.id: f for f in ir.features}
    sections = {x.id for x in plan.sections}
    used_letters = {x.label for x in plan.sections} | {d.letter for d in plan.manufacturing.datums}
    letters = [c for c in LETTERS if c not in used_letters]
    cand_view = {}
    by_id = {c.id: c for c in candidates}
    for sel in plan.dimension_selections:
        for fid in by_id[sel.candidate_id].feature_ids if sel.candidate_id in by_id else []:
            cand_view.setdefault(fid, sel.view_id)
    main = plan.primary_view.id if plan.primary_view.orientation not in PICTORIAL else (
        f"V-{plan.projected_views[0].value}" if plan.projected_views else None)
    items = []
    for fid in sorted(feature_ids):
        f = feats.get(fid)
        size = _feature_size(f) if f else None
        parent = cand_view.get(fid, main)
        if size is None or parent is None or parent in sections:
            continue
        p = feature_point(ir, fid, view_frame(ViewOrientation(parent.removeprefix("V-")), plan.view_frame))
        if p is None:
            continue
        items.append((fid, size, p, parent))
    out: list[DetailView] = []
    taken: set[str] = set()
    for fid, size, p, parent in items:
        if fid in taken or len(out) >= MAX_DETAILS or not letters:
            continue
        # the smallest drawing scale (> sheet scale) that prints the feature readably
        target = max(READABLE_MM / size, s * 1.5)
        options = sorted((scale_value(x), x) for x in DRAWING_SCALES if scale_value(x) >= target - 1e-9
                         and scale_value(x) <= MAX_DETAIL_SCALE)
        if not options:
            continue
        ds, label_scale = options[0]
        radius = max(DETAIL_DIAMETER_MM / 2 / ds, 1.5 * size)
        if 2 * radius * ds > MAX_DETAIL_DIAMETER_MM:
            continue
        group = [x for x in items if x[3] == parent and x[0] not in taken and math.dist(x[2], p) <= radius - x[1]]
        taken |= {x[0] for x in group}
        out.append(DetailView(id=f"V-DETAIL-{letters[len(out)]}", label=letters[len(out)], parent_view_id=parent,
                              feature_id=fid, scale=label_scale, radius=round(radius, 3),
                              center=tuple(round(x, 6) for x in p),
                              covers=sorted(x[0] for x in group)))
    return out


__all__ = ["plan_details", "feature_point", "scale_value"]
