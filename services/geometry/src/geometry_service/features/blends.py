"""Fillets (partial cylinders / tori tangent to neighbours) and chamfers."""

from __future__ import annotations

import numpy as np

from geometry_schema import ChamferFeature, Convexity, FilletFeature, Provenance, SurfaceType
from geometry_service import ids
from geometry_service.features.context import RecognitionContext
from geometry_service.features.cylindrical import FULL_TURN_TOL_DEG, _axial_range
from geometry_service.occt import geom as g

CHAMFER_MIN_INCLINATION_DEG = 10.0
CHAMFER_MAX_INCLINATION_DEG = 80.0
CHAMFER_MAX_WIDTH_RATIO = 0.5


def _tangent_neighbours(ctx: RecognitionContext, f: int) -> set[int]:
    return {
        nb
        for e in ctx.topo.face_edges[f]
        if ctx.convexity[e] == Convexity.TANGENT and (nb := ctx.neighbour_across(f, e)) is not None
    }


def recognize_fillets(ctx: RecognitionContext) -> list[FilletFeature]:
    out: list[FilletFeature] = []
    for f, fi in enumerate(ctx.faces):
        if f in ctx.claimed_faces or fi.concave is None:
            continue
        if fi.surface_type == SurfaceType.CYLINDER:
            if (fi.angular_extent_deg or 0.0) >= 360.0 - FULL_TURN_TOL_DEG:
                continue
            radius = fi.radius
        elif fi.surface_type == SurfaceType.TORUS:
            radius = fi.minor_radius
        else:
            continue
        if len(_tangent_neighbours(ctx, f)) < 2:
            continue
        ctx.claimed_faces.add(f)
        out.append(
            FilletFeature(
                id=ids.feature_id("FILLET", [fi.signature]),
                radius=radius,
                concave=bool(fi.concave),
                confidence=0.85,
                face_ids=[ctx.face_ids[f]],
                edge_ids=ctx.eids(
                    [e for e in ctx.topo.face_edges[f] if ctx.convexity[e] == Convexity.TANGENT]
                ),
                provenance=Provenance(method="partial_cylinder_or_torus+tangent_neighbours", exact=True),
            )
        )
    return out


def _plane_intersection_line(n1: g.Vec, p1: g.Vec, n2: g.Vec, p2: g.Vec, near: g.Vec):
    d = g.unit(g.cross(n1, n2))
    a = np.array([n1, n2, d])
    b = np.array([g.dot(n1, p1), g.dot(n2, p2), g.dot(d, near)])
    x = np.linalg.solve(a, b)
    return (float(x[0]), float(x[1]), float(x[2])), d


def recognize_chamfers(ctx: RecognitionContext) -> list[ChamferFeature]:
    out: list[ChamferFeature] = []
    out.extend(_planar_chamfers(ctx))
    out.extend(_conical_chamfers(ctx))
    return out


def _planar_chamfers(ctx: RecognitionContext) -> list[ChamferFeature]:
    out: list[ChamferFeature] = []
    for f, fi in enumerate(ctx.faces):
        if fi.surface_type != SurfaceType.PLANE or f in ctx.claimed_faces:
            continue
        # straight convex edges to planar neighbours, inclined to this face
        cands = []
        for e in ctx.topo.face_edges[f]:
            ei = ctx.edges[e]
            nb = ctx.neighbour_across(f, e)
            if nb is None or ei.curve_type.value != "LINE" or ctx.convexity[e] != Convexity.CONVEX:
                continue
            if ctx.faces[nb].surface_type != SurfaceType.PLANE:
                continue
            incl = g.angle_deg(fi.normal, ctx.faces[nb].normal)
            if CHAMFER_MIN_INCLINATION_DEG <= incl <= CHAMFER_MAX_INCLINATION_DEG:
                cands.append((e, nb))
        pair = None
        for i in range(len(cands)):
            for j in range(i + 1, len(cands)):
                (ea, na), (eb, nb) = cands[i], cands[j]
                if na == nb:
                    continue
                da = g.sub(ctx.edges[ea].end, ctx.edges[ea].start)
                db = g.sub(ctx.edges[eb].end, ctx.edges[eb].start)
                if g.parallel(da, db, ctx.tol.angular_deg) and not g.parallel(
                    ctx.faces[na].normal, ctx.faces[nb].normal, ctx.tol.angular_deg
                ):
                    pair = (ea, na, eb, nb)
                    break
            if pair:
                break
        if pair is None:
            continue
        ea, na, eb, nb = pair
        e_a, e_b = ctx.edges[ea], ctx.edges[eb]
        width = g.point_line_distance(e_b.mid, e_a.start, g.sub(e_a.end, e_a.start))
        length = max(e_a.length, e_b.length)
        if length <= 0 or width / length > CHAMFER_MAX_WIDTH_RATIO:
            continue
        fa, fb = ctx.faces[na], ctx.faces[nb]
        lp, ld = _plane_intersection_line(fa.normal, e_a.mid, fb.normal, e_b.mid, e_a.mid)
        d1 = g.point_line_distance(e_a.mid, lp, ld)
        d2 = g.point_line_distance(e_b.mid, lp, ld)
        # order legs deterministically by neighbour face id
        (id1, d1_, n1), (id2, d2_, _) = sorted(
            [(ctx.face_ids[na], d1, fa.normal), (ctx.face_ids[nb], d2, fb.normal)]
        )
        ctx.claimed_faces.add(f)
        out.append(
            ChamferFeature(
                id=ids.feature_id("CHAMFER", [fi.signature]),
                distance_1=d1_,
                distance_2=d2_,
                angle_deg=g.angle_deg(fi.normal, n1),
                adjacent_face_ids=[id1, id2],
                confidence=0.75,
                face_ids=[ctx.face_ids[f]],
                edge_ids=ctx.eids([ea, eb]),
                provenance=Provenance(method="inclined_narrow_plane_between_planes", exact=True),
            )
        )
    return out


def _conical_chamfers(ctx: RecognitionContext) -> list[ChamferFeature]:
    out: list[ChamferFeature] = []
    for f, fi in enumerate(ctx.faces):
        if fi.surface_type != SurfaceType.CONE or f in ctx.claimed_faces or fi.concave:
            continue
        d = g.canonical_direction(g.unit(fi.axis_dir))
        nbrs = ctx.topo.adjacent_faces(f)
        cyl = [
            nb
            for nb in nbrs
            if ctx.faces[nb].surface_type == SurfaceType.CYLINDER
            and g.parallel(ctx.faces[nb].axis_dir, d, ctx.tol.angular_deg)
            and g.point_line_distance(ctx.faces[nb].origin, fi.origin, d) < ctx.tol.linear
        ]
        cap = [
            nb
            for nb in nbrs
            if ctx.faces[nb].surface_type == SurfaceType.PLANE
            and g.parallel(ctx.faces[nb].normal, d, ctx.tol.angular_deg)
        ]
        if not cyl or not cap:
            continue
        a0, a1 = _axial_range(ctx, [f], fi.origin, d)
        radii = [ctx.edges[e].circle_radius for e in ctx.topo.face_edges[f] if ctx.edges[e].circle_radius]
        if len(radii) < 2:
            continue
        axial, radial = a1 - a0, max(radii) - min(radii)
        ctx.claimed_faces.add(f)
        out.append(
            ChamferFeature(
                id=ids.feature_id("CHAMFER", [fi.signature]),
                distance_1=axial,
                distance_2=radial,
                angle_deg=abs(fi.half_angle_deg or 0.0),
                adjacent_face_ids=sorted([ctx.face_ids[cyl[0]], ctx.face_ids[cap[0]]]),
                confidence=0.85,
                face_ids=[ctx.face_ids[f]],
                provenance=Provenance(method="convex_cone_between_cylinder_and_cap", exact=True),
                notes=["distance_1 = axial leg, distance_2 = radial leg"],
            )
        )
    return out
