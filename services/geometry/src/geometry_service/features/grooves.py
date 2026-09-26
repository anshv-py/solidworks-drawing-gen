"""Face grooves (O-ring glands): annular grooves of rectangular section cut into a planar face.

Recognized from the cylinder groups before holes and bosses, so that the groove's inner wall is not
taken for a short boss: a convex full cylinder (inner wall) and a concave full cylinder (outer wall) on
one axis, with the same axial extent, both bounding one planar floor perpendicular to the axis. Radial
grooves on shafts / in bores are not recognized yet.
"""

from __future__ import annotations

from geometry_schema import Axis, GrooveFeature, Provenance, SurfaceType
from geometry_service import ids
from geometry_service.features.context import RecognitionContext
from geometry_service.features.cylindrical import CylGroup, _same_line
from geometry_service.occt import geom as g


def recognize_face_grooves(ctx: RecognitionContext, groups: list[CylGroup]) -> tuple[list[GrooveFeature], list[CylGroup]]:
    """-> (grooves, the cylinder groups not used by a groove)."""
    tol = ctx.tol.linear
    grooves: list[GrooveFeature] = []
    used: set[int] = set()
    inner_walls = [gr for gr in groups if not gr.concave and gr.full]
    outer_walls = [gr for gr in groups if gr.concave and gr.full]
    for inner in inner_walls:
        for outer in outer_walls:
            if id(outer) in used or id(inner) in used or outer.radius <= inner.radius + tol:
                continue
            if not _same_line(ctx, inner.origin, inner.direction, outer.origin, outer.direction):
                continue
            # same axial extent (in the inner wall's parametrisation)
            o_lo, o_hi = sorted(g.project_on_axis(outer.point_at(a), inner.origin, inner.direction)
                                for a in (outer.a_min, outer.a_max))
            if abs(o_lo - inner.a_min) > tol or abs(o_hi - inner.a_max) > tol:
                continue
            floors = []
            for f in {x for w in (*inner.faces, *outer.faces) for e in ctx.topo.face_edges[w]
                      for x in ctx.topo.edge_faces[e]}:
                fi = ctx.faces[f]
                if fi.surface_type != SurfaceType.PLANE or not g.parallel(fi.normal, inner.direction, ctx.tol.angular_deg):
                    continue
                touches_in = any(ctx.edges_between(f, w) for w in inner.faces)
                touches_out = any(ctx.edges_between(f, w) for w in outer.faces)
                if touches_in and touches_out:
                    floors.append(f)
            if len(floors) != 1:
                continue
            floor = floors[0]
            a_floor = g.project_on_axis(ctx.faces[floor].centroid, inner.origin, inner.direction)
            at_hi = abs(a_floor - inner.a_max) < tol
            a_open = inner.a_min if at_hi else inner.a_max
            into = inner.direction if at_hi else g.scale(inner.direction, -1.0)
            depth = inner.a_max - inner.a_min
            faces = sorted({*inner.faces, *outer.faces, floor})
            ctx.claimed_faces.update(faces)
            used |= {id(inner), id(outer)}
            grooves.append(GrooveFeature(
                id=ids.feature_id("GROOVE", ctx.signatures(faces)),
                axis=Axis(origin=inner.point_at(a_open), direction=into),
                inner_diameter=2 * inner.radius, outer_diameter=2 * outer.radius,
                width=outer.radius - inner.radius, depth=depth, floor_face_id=ctx.face_ids[floor],
                confidence=0.9, face_ids=ctx.ids(faces),
                provenance=Provenance(method="coaxial_convex_concave_walls+annular_floor", exact=True),
                notes=["annular face groove (typically an O-ring gland)"],
            ))
    return grooves, [gr for gr in groups if id(gr) not in used]


__all__ = ["recognize_face_grooves"]
