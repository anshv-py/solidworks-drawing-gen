"""Slots and pockets."""

from __future__ import annotations

import math

from geometry_schema import Convexity, PocketFeature, Provenance, SlotFeature, SurfaceType
from geometry_service import ids
from geometry_service.features.context import RecognitionContext
from geometry_service.features.cylindrical import CylGroup, _axial_range
from geometry_service.occt import geom as g

HALF_TURN_TOL_DEG = 2.0


def recognize_slots(ctx: RecognitionContext, groups: list[CylGroup]) -> list[SlotFeature]:
    halves = [
        gr
        for gr in groups
        if gr.concave
        and abs(gr.coverage_deg - 180.0) <= HALF_TURN_TOL_DEG
        and not ctx.claimed_faces.intersection(gr.faces)
    ]
    slots: list[SlotFeature] = []
    used: set[int] = set()
    for i, a in enumerate(halves):
        if i in used:
            continue
        for j in range(i + 1, len(halves)):
            b = halves[j]
            if j in used or abs(a.radius - b.radius) > ctx.tol.linear:
                continue
            if not g.parallel(a.direction, b.direction, ctx.tol.angular_deg):
                continue
            # axis-to-axis vector perpendicular to the axes
            v = g.sub(b.origin, a.origin)
            v = g.sub(v, g.scale(a.direction, g.dot(v, a.direction)))
            cd = g.norm(v)
            if cd < ctx.tol.linear:
                continue  # coaxial - not a slot
            walls = _connecting_walls(ctx, a, b)
            if len(walls) != 2:
                continue
            used.update((i, j))
            length_dir = g.canonical_direction(g.unit(v))
            o, d = a.origin, a.direction
            lo = max(a.a_min, _axial_range(ctx, b.faces, o, d)[0])
            hi = min(a.a_max, _axial_range(ctx, b.faces, o, d)[1])
            half = g.scale(g.unit(v), 0.5 * cd)
            center = g.add(a.point_at(0.5 * (lo + hi)), half)
            clf = ctx.classifier_for_face(a.faces[0])
            step = ctx.tol.probe * 4
            open_lo = bool(clf and clf.outside(g.add(a.point_at(lo - step), half)))
            open_hi = bool(clf and clf.outside(g.add(a.point_at(hi + step), half)))
            through = open_lo and open_hi
            depth_dir = g.scale(d, -1.0) if open_hi else d
            face_idx = sorted(set(a.faces) | set(b.faces) | set(walls))
            floor = None if through else _floor_between(ctx, face_idx, d)
            if floor is not None:
                face_idx = sorted(set(face_idx) | {floor})
            ctx.claimed_faces.update(face_idx)
            slots.append(
                SlotFeature(
                    id=ids.feature_id("SLOT", ctx.signatures(face_idx)),
                    width=2 * a.radius,
                    length=cd + 2 * a.radius,
                    center_distance=cd,
                    depth=hi - lo,
                    through=through,
                    length_direction=length_dir,
                    depth_direction=depth_dir,
                    center=center,
                    confidence=0.9,
                    face_ids=ctx.ids(face_idx),
                    provenance=Provenance(method="paired_half_cylinders+tangent_walls", exact=True),
                )
            )
            break
    return slots


def _connecting_walls(ctx: RecognitionContext, a: CylGroup, b: CylGroup) -> list[int]:
    """Planar faces tangent-adjacent to both half cylinders."""
    walls = []
    a_nbrs = {nb for f in a.faces for nb in ctx.topo.adjacent_faces(f)}
    b_nbrs = {nb for f in b.faces for nb in ctx.topo.adjacent_faces(f)}
    for w in sorted(a_nbrs & b_nbrs):
        if ctx.faces[w].surface_type != SurfaceType.PLANE:
            continue
        tangent = all(
            ctx.convexity[e] == Convexity.TANGENT
            for f in a.faces + b.faces
            for e in ctx.edges_between(w, f)
        )
        # wall must contain the axis direction (normal perpendicular to the axis)
        if tangent and abs(g.dot(ctx.faces[w].normal, a.direction)) < math.sin(
            math.radians(ctx.tol.angular_deg)
        ):
            walls.append(w)
    return walls


def _floor_between(ctx: RecognitionContext, faces: list[int], axis: g.Vec) -> int | None:
    common = None
    for f in faces:
        nb = set(ctx.topo.adjacent_faces(f))
        common = nb if common is None else common & nb
    for f in sorted(common or ()):
        fi = ctx.faces[f]
        if fi.surface_type == SurfaceType.PLANE and g.parallel(fi.normal, axis, ctx.tol.angular_deg):
            return f
    return None


def _inward_edge(ctx: RecognitionContext, f: int, e: int) -> bool:
    """Edge where the neighbour rises from the floor (concave, or tangent to a concave blend)."""
    conv = ctx.convexity[e]
    if conv == Convexity.CONCAVE:
        return True
    if conv == Convexity.TANGENT:
        nb = ctx.neighbour_across(f, e)
        if nb is None:
            return False
        fi = ctx.faces[nb]
        if fi.surface_type in (SurfaceType.CYLINDER, SurfaceType.TORUS, SurfaceType.CONE):
            return bool(fi.concave)
    return False


def recognize_pockets(ctx: RecognitionContext) -> list[PocketFeature]:
    pockets: list[PocketFeature] = []
    for f, fi in enumerate(ctx.faces):
        if fi.surface_type != SurfaceType.PLANE or f in ctx.claimed_faces:
            continue
        outer = [e for e in ctx.outer_wire_edges(f) if not ctx.topo.is_seam(e)]
        if len(outer) < 2 or not all(_inward_edge(ctx, f, e) for e in outer):
            continue
        walls = sorted({nb for e in outer if (nb := ctx.neighbour_across(f, e)) is not None})
        if not walls or set(walls) <= ctx.claimed_faces:
            continue  # e.g. bottom of a blind hole
        n = g.unit(fi.normal)
        floor_level = g.dot(fi.centroid, n)
        wall_pts = [p for w in walls for p in ctx.face_points(w)]
        depth = max(g.dot(p, n) for p in wall_pts) - floor_level
        if depth <= ctx.tol.linear:
            continue
        # extents of the floor outline along the longest straight edge direction
        floor_pts = ctx.face_points(f)
        lines = [e for e in outer if ctx.edges[e].curve_type.value == "LINE"]
        if lines:
            longest = max(lines, key=lambda e: (round(ctx.edges[e].length, 6), ctx.edges[e].signature))
            u = g.unit(g.sub(ctx.edges[longest].end, ctx.edges[longest].start))
        else:
            ref = (0.0, 1.0, 0.0) if g.parallel(n, (1.0, 0.0, 0.0), 1.0) else (1.0, 0.0, 0.0)
            u = g.unit(g.cross(n, ref))
        u = g.canonical_direction(u)
        v = g.unit(g.cross(n, u))
        pu = [g.dot(p, u) for p in floor_pts]
        pv = [g.dot(p, v) for p in floor_pts]
        length, width = max(pu) - min(pu), max(pv) - min(pv)
        cu, cv = 0.5 * (max(pu) + min(pu)), 0.5 * (max(pv) + min(pv))
        center = g.add(g.add(g.scale(u, cu), g.scale(v, cv)), g.scale(n, floor_level))
        if width > length:
            length, width, u = width, length, g.canonical_direction(v)
        corner_r = sorted(
            {
                round(ctx.faces[w].radius, 6)
                for w in walls
                if ctx.faces[w].surface_type == SurfaceType.CYLINDER
                and ctx.faces[w].concave
                and g.parallel(ctx.faces[w].axis_dir, n, ctx.tol.angular_deg)
            }
        )
        face_idx = sorted({f, *walls})
        ctx.claimed_faces.add(f)
        pockets.append(
            PocketFeature(
                id=ids.feature_id("POCKET", ctx.signatures(face_idx)),
                floor_face_id=ctx.face_ids[f],
                floor_normal=n,
                depth=depth,
                length=length,
                width=width,
                length_direction=u,
                center=center,
                corner_radius=corner_r[0] if len(corner_r) == 1 else None,
                confidence=0.85,
                face_ids=ctx.ids(face_idx),
                edge_ids=ctx.eids(outer),
                provenance=Provenance(method="concave_floor_outline", exact=True),
                notes=[] if len(corner_r) <= 1 else ["multiple wall corner radii"],
            )
        )
    return pockets
