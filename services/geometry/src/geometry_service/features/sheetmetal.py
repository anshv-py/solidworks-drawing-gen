"""Sheet-metal bends and the constant-thickness test.

A bend is a partial concave cylinder (inner, radius r) and a partial convex cylinder (outer, radius
r + t) on the same axis with the same axial extent. The part counts as sheet metal when it has at least
one bend, every bend has the same thickness t, and the planar faces pair up (parallel, opposite, t
apart) for at least ``PAIRED_AREA`` of the planar area. Recognized before fillets, which would
otherwise take the two bend faces for a fillet and a round.
"""

from __future__ import annotations

from geometry_schema import Axis, BendFeature, Provenance, SheetMetal, SurfaceType
from geometry_service import ids
from geometry_service.features.context import RecognitionContext
from geometry_service.features.cylindrical import CylGroup, _same_line
from geometry_service.occt import geom as g

PAIRED_AREA = 0.8


def _paired_area(ctx: RecognitionContext, t: float) -> float:
    planes = [f for f in ctx.faces if f.surface_type == SurfaceType.PLANE]
    total = sum(f.area for f in planes) or 1.0
    paired = 0.0
    for f in planes:
        for o in planes:
            if o is f or g.dot(f.normal, o.normal) > -1 + 1e-6:
                continue
            gap = abs(g.dot(g.sub(o.centroid, f.centroid), f.normal))
            if abs(gap - t) < ctx.tol.linear * 10:
                paired += f.area
                break
    return paired / total


def recognize_bends(ctx: RecognitionContext, groups: list[CylGroup]):
    """-> (bends, SheetMetal | None, the cylinder groups not used by a bend)."""
    tol = ctx.tol.linear
    bends: list[BendFeature] = []
    used: set[int] = set()
    inners = [gr for gr in groups if gr.concave and not gr.full]
    outers = [gr for gr in groups if not gr.concave and not gr.full]
    for inner in inners:
        for outer in outers:
            if id(outer) in used or outer.radius <= inner.radius + tol:
                continue
            if not _same_line(ctx, inner.origin, inner.direction, outer.origin, outer.direction):
                continue
            o_lo, o_hi = sorted(g.project_on_axis(outer.point_at(a), inner.origin, inner.direction)
                                for a in (outer.a_min, outer.a_max))
            if abs(o_lo - inner.a_min) > tol or abs(o_hi - inner.a_max) > tol:
                continue
            if abs(inner.coverage_deg - outer.coverage_deg) > 1.0:
                continue
            t = outer.radius - inner.radius
            faces = sorted({*inner.faces, *outer.faces})
            used |= {id(inner), id(outer)}
            bends.append(BendFeature(
                id=ids.feature_id("BEND", ctx.signatures(faces)),
                axis=Axis(origin=inner.point_at(inner.a_min), direction=inner.direction),
                inner_radius=inner.radius, thickness=t, angle_deg=round(inner.coverage_deg, 6),
                length=inner.a_max - inner.a_min, inner_face_ids=ctx.ids(inner.faces),
                outer_face_ids=ctx.ids(outer.faces), confidence=0.9, face_ids=ctx.ids(faces),
                provenance=Provenance(method="coaxial_partial_cylinders_r_r+t", exact=True),
                notes=["sheet-metal bend"],
            ))
            break
    if not bends:
        return [], None, groups
    ts = {round(b.thickness, 4) for b in bends}
    if len(ts) != 1 or _paired_area(ctx, bends[0].thickness) < PAIRED_AREA:
        return [], None, groups  # coaxial fillet + round on a machined part, not formed sheet
    for gr in groups:
        if id(gr) in used:
            ctx.claimed_faces.update(gr.faces)
    info = SheetMetal(thickness=bends[0].thickness, bend_ids=sorted(b.id for b in bends))
    return bends, info, [gr for gr in groups if id(gr) not in used]


__all__ = ["recognize_bends"]
