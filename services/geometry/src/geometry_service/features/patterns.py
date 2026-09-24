"""Hole patterns: circular, rectangular (grid) and linear."""

from __future__ import annotations

import math
from collections import defaultdict

from geometry_schema import (
    BossFeature,
    FeatureType,
    HoleFeature,
    PatternFeature,
    PatternType,
    Provenance,
)
from geometry_service import ids
from geometry_service.features.context import RecognitionContext
from geometry_service.occt import geom as g

MIN_MEMBERS = 3


def _frame(n: g.Vec) -> tuple[g.Vec, g.Vec]:
    ref = (0.0, 1.0, 0.0) if g.parallel(n, (1.0, 0.0, 0.0), 1.0) else (1.0, 0.0, 0.0)
    u = g.unit(g.cross(n, ref))
    u = g.canonical_direction(u)
    return u, g.unit(g.cross(n, u))


def _key(ctx: RecognitionContext, h: HoleFeature) -> tuple:
    r = lambda x: round(x / ctx.tol.linear) if x is not None else None  # noqa: E731
    cb = (r(h.counterbore.diameter), r(h.counterbore.depth)) if h.counterbore else None
    cs = (r(h.countersink.diameter), round(h.countersink.angle_deg, 1)) if h.countersink else None
    axis = tuple(round(c, 4) for c in g.canonical_direction(h.axis.direction))
    return (r(h.diameter), h.kind.value, h.through, cb, cs, axis)


def _circumcentre(a, b, c):
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
    uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
    return ux, uy


def _equal_steps(values: list[float], tol: float) -> float | None:
    steps = [b - a for a, b in zip(values, values[1:])]
    if steps and all(abs(s - steps[0]) < tol for s in steps) and steps[0] > tol:
        return steps[0]
    return None


def _clusters(values: list[float], tol: float) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _circular(ctx, pts2, centres_ok):
    n = len(pts2)
    order = sorted(range(n), key=lambda i: pts2[i])
    c = _circumcentre(pts2[order[0]], pts2[order[n // 2]], pts2[order[-1]])
    if c is None:
        return None
    radii = [math.dist(p, c) for p in pts2]
    if max(radii) - min(radii) > ctx.tol.linear:
        return None
    angles = sorted(math.degrees(math.atan2(p[1] - c[1], p[0] - c[0])) % 360.0 for p in pts2)
    step = _equal_steps(angles, 0.1)
    full = abs(360.0 / n - (step or -1)) < 0.1 if step else False
    if step is None:
        # maybe wraps around 0 deg: check steps including the wrap
        wrapped = angles[1:] + [angles[0] + 360.0]
        diffs = [b - a for a, b in zip(angles, wrapped)]
        if all(abs(d - 360.0 / n) < 0.1 for d in diffs):
            step, full = 360.0 / n, True
    if step is None:
        return None
    return c, radii[0], step, full


def _grid(ctx, pts2):
    n = len(pts2)
    base = min(pts2)
    dirs = []
    for p in sorted(pts2):
        if p == base:
            continue
        v = (p[0] - base[0], p[1] - base[1])
        ln = math.hypot(*v)
        if ln > ctx.tol.linear:
            dirs.append((v[0] / ln, v[1] / ln))
    for d1 in dirs:
        d2 = (-d1[1], d1[0])
        c1 = [p[0] * d1[0] + p[1] * d1[1] for p in pts2]
        c2 = [p[0] * d2[0] + p[1] * d2[1] for p in pts2]
        k1, k2 = _clusters(c1, ctx.tol.linear), _clusters(c2, ctx.tol.linear)
        if len(k1) < 2 or len(k2) < 2 or len(k1) * len(k2) != n:
            continue
        s1, s2 = _equal_steps(k1, ctx.tol.linear), _equal_steps(k2, ctx.tol.linear)
        if s1 is None or s2 is None:
            continue
        cells = {(round(a / ctx.tol.linear), round(b / ctx.tol.linear)) for a, b in zip(c1, c2)}
        if len(cells) != n:
            continue
        return d1, d2, (len(k1), len(k2)), (s1, s2)
    return None


def _linear(ctx, pts2):
    a, b = min(pts2), max(pts2)
    v = (b[0] - a[0], b[1] - a[1])
    ln = math.hypot(*v)
    if ln < ctx.tol.linear:
        return None
    d = (v[0] / ln, v[1] / ln)
    for p in pts2:
        off = (p[0] - a[0]) * -d[1] + (p[1] - a[1]) * d[0]
        if abs(off) > ctx.tol.linear:
            return None
    t = sorted((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1] for p in pts2)
    step = _equal_steps(t, ctx.tol.linear)
    return (d, step) if step else None


def recognize_hole_patterns(
    ctx: RecognitionContext, holes: list[HoleFeature], bosses: list[BossFeature]
) -> list[PatternFeature]:
    groups: dict[tuple, list[HoleFeature]] = defaultdict(list)
    for h in holes:
        groups[_key(ctx, h)].append(h)
    out: list[PatternFeature] = []
    other_axes = [(f.axis.origin, f.axis.direction) for f in [*holes, *bosses]]
    for members in groups.values():
        if len(members) < MIN_MEMBERS:
            continue
        members = sorted(members, key=lambda h: h.id)
        n_axis = g.canonical_direction(g.unit(members[0].axis.direction))
        u, v = _frame(n_axis)
        level = g.dot(members[0].axis.origin, n_axis)
        pts2 = [(g.dot(h.axis.origin, u), g.dot(h.axis.origin, v)) for h in members]

        def lift(p2):
            return g.add(g.add(g.scale(u, p2[0]), g.scale(v, p2[1])), g.scale(n_axis, level))

        common = dict(
            member_feature_ids=[h.id for h in members],
            member_type=FeatureType.HOLE,
            count=len(members),
            face_ids=sorted(fid for h in members for fid in h.face_ids),
        )
        circ = _circular(ctx, pts2, None)
        grid = _grid(ctx, pts2)
        centre_on_axis = False
        if circ:
            c3 = lift(circ[0])
            centre_on_axis = any(
                g.parallel(d, n_axis, ctx.tol.angular_deg) and g.point_line_distance(c3, o, d) < ctx.tol.linear
                for o, d in other_axes
            )
        pid = ids.feature_id("PAT", [h.id for h in members])
        if circ and (centre_on_axis or not grid):
            c2, radius, step, full = circ
            out.append(
                PatternFeature(
                    id=pid,
                    pattern_type=PatternType.CIRCULAR,
                    center=lift(c2),
                    axis_direction=n_axis,
                    pitch_circle_diameter=2 * radius,
                    angular_step_deg=step,
                    confidence=0.95,
                    provenance=Provenance(method="equal_radius_equal_angle", exact=True),
                    notes=[] if full else ["partial circular pattern (does not close 360 deg)"],
                    **common,
                )
            )
        elif grid:
            d1, d2, counts, pitches = grid
            dirs3 = [g.canonical_direction(g.add(g.scale(u, d[0]), g.scale(v, d[1]))) for d in (d1, d2)]
            order = sorted(range(2), key=lambda i: pitches[i])
            out.append(
                PatternFeature(
                    id=pid,
                    pattern_type=PatternType.RECTANGULAR,
                    directions=[dirs3[i] for i in order],
                    pitches=[pitches[i] for i in order],
                    counts=[counts[i] for i in order],
                    confidence=0.95,
                    provenance=Provenance(method="grid_clustering", exact=True),
                    **common,
                )
            )
        elif lin := _linear(ctx, pts2):
            d, step = lin
            out.append(
                PatternFeature(
                    id=pid,
                    pattern_type=PatternType.LINEAR,
                    directions=[g.canonical_direction(g.add(g.scale(u, d[0]), g.scale(v, d[1])))],
                    pitches=[step],
                    counts=[len(members)],
                    confidence=0.95,
                    provenance=Provenance(method="collinear_equal_pitch", exact=True),
                    **common,
                )
            )
    return sorted(out, key=lambda p: p.id)
