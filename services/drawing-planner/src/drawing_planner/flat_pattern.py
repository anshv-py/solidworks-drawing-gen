"""Flat pattern of a sheet-metal part (EX 5: mandatory for sheet metal).

Supported: a chain of flat segments joined by bends whose axes are all parallel (L, U, Z, hat profiles
extruded along the bend axis). Each flat segment is a pair of parallel faces t apart; bends link
segments through shared edges. Developed length = segment lengths + bend allowances, the neutral fibre
per DIN 6935 (k = 0.65 + 0.5 log10(r / s), capped at 1; neutral radius r + k s / 2). Bend direction: UP
when the bend's inside faces the viewer of the flat pattern (the viewer sees segment 0 from the side of
its first bend's inside). Holes square to a segment are mapped onto the flat. Anything else returns None
with the reason (the flat pattern is then reported as not drawn).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from geometry_schema import FeatureType, GeometryIR, SurfaceType

_EPS = 1e-6


def din6935_k(radius: float, thickness: float) -> float:
    return 1.0 if radius / thickness >= 5 else min(1.0, 0.65 + 0.5 * math.log10(radius / thickness))


@dataclass
class FlatBend:
    x: float  # bend centre line position on the flat
    angle_deg: float
    inner_radius: float
    up: bool
    allowance: float
    k: float
    bend_id: str


@dataclass
class FlatPattern:
    length: float
    width: float
    thickness: float
    bends: list[FlatBend] = field(default_factory=list)
    holes: list[tuple[float, float, float, str]] = field(default_factory=list)  # x, y, diameter, feature id


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def compute_flat_pattern(ir: GeometryIR) -> tuple[FlatPattern | None, str]:
    sm = ir.sheet_metal
    if sm is None:
        return None, "not sheet metal"
    t = sm.thickness
    feats = {f.id: f for f in ir.features}
    bends = [feats[b] for b in sm.bend_ids]
    a = bends[0].axis.direction
    if any(abs(abs(_dot(b.axis.direction, a)) - 1) > _EPS for b in bends):
        return None, "bends with non-parallel axes (flat pattern not supported yet)"
    faces = {f.id: f for f in ir.faces}
    edges = {e.id: e for e in ir.edges}
    planes = [f for f in ir.faces if f.surface_type == SurfaceType.PLANE and abs(_dot(f.surface.normal, a)) < _EPS]
    # segments: parallel opposite faces t apart that overlap
    segments: list[tuple] = []
    used: set[str] = set()
    for f in sorted(planes, key=lambda f: f.id):
        if f.id in used:
            continue
        for o in planes:
            if o.id == f.id or o.id in used or _dot(f.surface.normal, o.surface.normal) > -1 + _EPS:
                continue
            gap = abs(_dot([o.centroid[i] - f.centroid[i] for i in range(3)], f.surface.normal))
            if abs(gap - t) < 1e-3:
                segments.append((f, o))
                used |= {f.id, o.id}
                break

    def touches(face, bend_faces) -> bool:
        return any(eid in face.edge_ids for bf in bend_faces for eid in faces[bf].edge_ids)

    links = {}  # bend id -> segment indices it joins
    for b in bends:
        segs = [i for i, (f, o) in enumerate(segments)
                if touches(f, b.inner_face_ids + b.outer_face_ids) or touches(o, b.inner_face_ids + b.outer_face_ids)]
        if len(segs) != 2:
            return None, f"bend {b.id} does not join two flat segments"
        links[b.id] = segs
    degree = {i: sum(i in s for s in links.values()) for i in range(len(segments))}
    if any(d > 2 for d in degree.values()) or len(segments) != len(bends) + 1:
        return None, "branched sheet-metal part (flat pattern not supported yet)"
    start = min((i for i, d in degree.items() if d == 1), key=lambda i: segments[i][0].id)
    order, bend_order, cur = [start], [], start
    while len(order) < len(segments):
        b = next(bid for bid, s in links.items() if cur in s and bid not in bend_order)
        bend_order.append(b)
        cur = next(i for i in links[b] if i != cur)
        order.append(cur)

    def extent(face, u) -> tuple[float, float]:
        pts = [p for eid in face.edge_ids if eid in edges for p in (edges[eid].start, edges[eid].end)]
        vals = [_dot(p, u) for p in pts]
        return min(vals), max(vals)

    all_pts = [p for e in ir.edges for p in (e.start, e.end)]
    y0 = min(_dot(p, a) for p in all_pts)
    width = max(_dot(p, a) for p in all_pts) - y0
    out = FlatPattern(length=0.0, width=round(width, 6), thickness=t)
    x = 0.0
    viewer = None  # the face of the current segment that faces the flat-pattern viewer
    for k, si in enumerate(order):
        f, o = segments[si]
        u = _cross(f.surface.normal, a)
        nxt = feats[bend_order[k]] if k < len(bend_order) else None
        prv = feats[bend_order[k - 1]] if k > 0 else None
        ref = nxt.axis.origin if nxt else prv.axis.origin
        towards_next = _dot([ref[i] - f.centroid[i] for i in range(3)], u) > 0
        if (nxt is not None) != towards_next:
            u = tuple(-c for c in u)
        lo, hi = extent(f, u)
        seg_len = hi - lo
        if k == 0:
            viewer = f if touches(f, nxt.inner_face_ids) else o
        elif prv is not None:
            side_inner = touches(viewer_prev, prv.inner_face_ids)
            viewer = f if touches(f, prv.inner_face_ids if side_inner else prv.outer_face_ids) else o
        for h in ir.features:
            if h.type != FeatureType.HOLE or abs(abs(_dot(h.axis.direction, f.surface.normal)) - 1) > _EPS:
                continue
            c = h.axis.origin
            if abs(_dot([c[i] - f.centroid[i] for i in range(3)], f.surface.normal)) > t + 1e-3:
                continue
            s = _dot(c, u) - lo
            if -_EPS <= s <= seg_len + _EPS:
                out.holes.append((round(x + s, 6), round(_dot(c, a) - y0, 6), h.diameter, h.id))
        x += seg_len
        if nxt is not None:
            kk = din6935_k(nxt.inner_radius, t)
            ba = math.radians(nxt.angle_deg) * (nxt.inner_radius + kk * t / 2)
            out.bends.append(FlatBend(x=round(x + ba / 2, 6), angle_deg=nxt.angle_deg, inner_radius=nxt.inner_radius,
                                      up=touches(viewer, nxt.inner_face_ids), allowance=round(ba, 6), k=round(kk, 4),
                                      bend_id=nxt.id))
            x += ba
        viewer_prev = viewer
    out.length = round(x, 6)
    return out, ""


__all__ = ["FlatBend", "FlatPattern", "compute_flat_pattern", "din6935_k"]
