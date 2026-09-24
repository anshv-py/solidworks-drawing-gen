"""Holes (simple / counterbore / countersink) and cylindrical bosses."""

from __future__ import annotations

from dataclasses import dataclass, field

from geometry_schema import (
    Axis,
    BossFeature,
    Convexity,
    Counterbore,
    Countersink,
    HoleFeature,
    HoleKind,
    Provenance,
    SurfaceType,
)
from geometry_service import ids
from geometry_service.features.context import RecognitionContext
from geometry_service.occt import geom as g

FULL_TURN_TOL_DEG = 1.0


@dataclass
class CylGroup:
    """Faces lying on one cylinder (STEP often splits a hole into two half faces)."""

    faces: list[int]
    radius: float
    origin: g.Vec
    direction: g.Vec  # canonical
    concave: bool
    coverage_deg: float
    a_min: float = 0.0  # axial range (projection on direction from origin)
    a_max: float = 0.0
    kind: SurfaceType = SurfaceType.CYLINDER
    extra: dict = field(default_factory=dict)

    @property
    def full(self) -> bool:
        return self.coverage_deg >= 360.0 - FULL_TURN_TOL_DEG

    def point_at(self, a: float) -> g.Vec:
        return g.add(self.origin, g.scale(self.direction, a))


def _same_line(ctx: RecognitionContext, o1: g.Vec, d1: g.Vec, o2: g.Vec, d2: g.Vec) -> bool:
    return g.parallel(d1, d2, ctx.tol.angular_deg) and g.point_line_distance(o2, o1, d1) < ctx.tol.linear


def _axial_range(ctx: RecognitionContext, faces: list[int], origin: g.Vec, direction: g.Vec):
    proj = [g.project_on_axis(p, origin, direction) for f in faces for p in ctx.face_points(f)]
    return min(proj), max(proj)


def group_cylinders(ctx: RecognitionContext) -> list[CylGroup]:
    """Group cylinder faces by (axis line, radius, concavity) and connectivity/axial contact."""
    cands = [
        f
        for f, fi in enumerate(ctx.faces)
        if fi.surface_type == SurfaceType.CYLINDER and fi.concave is not None
    ]
    groups: list[CylGroup] = []
    for f in cands:
        fi = ctx.faces[f]
        d = g.canonical_direction(g.unit(fi.axis_dir))
        a0, a1 = _axial_range(ctx, [f], fi.origin, d)
        placed = False
        for grp in groups:
            if (
                grp.concave == fi.concave
                and abs(grp.radius - fi.radius) < ctx.tol.linear
                and _same_line(ctx, grp.origin, grp.direction, fi.origin, d)
            ):
                b0, b1 = _axial_range(ctx, [f], grp.origin, grp.direction)
                touching = b0 <= grp.a_max + ctx.tol.linear and b1 >= grp.a_min - ctx.tol.linear
                if touching:
                    grp.faces.append(f)
                    grp.a_min, grp.a_max = min(grp.a_min, b0), max(grp.a_max, b1)
                    placed = True
                    break
        if not placed:
            groups.append(
                CylGroup(
                    faces=[f],
                    radius=fi.radius,
                    origin=fi.origin,
                    direction=d,
                    concave=bool(fi.concave),
                    coverage_deg=0.0,  # computed below
                    a_min=a0,
                    a_max=a1,
                )
            )
    # coverage: split faces covering the same axial band add up to 360
    for grp in groups:
        grp.coverage_deg = _coverage(ctx, grp)
    groups.sort(key=lambda gr: sorted(ctx.faces[f].signature for f in gr.faces))
    return groups


def _coverage(ctx: RecognitionContext, grp: CylGroup) -> float:
    # Faces stacked axially (e.g. a hole interrupted by a cross hole) each cover their own band;
    # take the max coverage over axial bands rather than the plain sum.
    bands: dict[tuple[float, float], float] = {}
    for f in grp.faces:
        b = _axial_range(ctx, [f], grp.origin, grp.direction)
        key = (round(b[0], 3), round(b[1], 3))
        bands[key] = bands.get(key, 0.0) + (ctx.faces[f].angular_extent_deg or 0.0)
    return min(360.0, max(bands.values())) if bands else 0.0


def _coaxial_cones(ctx: RecognitionContext, grp: CylGroup, concave: bool) -> list[int]:
    out = []
    for f, fi in enumerate(ctx.faces):
        if fi.surface_type != SurfaceType.CONE or fi.concave != concave or f in ctx.claimed_faces:
            continue
        if _same_line(ctx, grp.origin, grp.direction, fi.origin, g.canonical_direction(fi.axis_dir)):
            c0, c1 = _axial_range(ctx, [f], grp.origin, grp.direction)
            if c0 <= grp.a_max + ctx.tol.linear and c1 >= grp.a_min - ctx.tol.linear:
                out.append(f)
    return out


def _cone_radii(ctx: RecognitionContext, f: int) -> tuple[float, float]:
    radii = [
        ctx.edges[e].circle_radius
        for e in ctx.topo.face_edges[f]
        if ctx.edges[e].circle_radius is not None
    ]
    return (min(radii), max(radii)) if radii else (0.0, 0.0)


def _is_open(ctx: RecognitionContext, grp: CylGroup, a: float, outward: float) -> bool:
    clf = ctx.classifier_for_face(grp.faces[0])
    if clf is None:
        return False
    probe = grp.point_at(a + outward * ctx.tol.probe * 4)
    return clf.outside(probe)


def recognize_holes(ctx: RecognitionContext, groups: list[CylGroup]) -> list[HoleFeature]:
    holes: list[HoleFeature] = []
    concave_full = [gr for gr in groups if gr.concave and gr.full]
    # stacks: coaxial full concave groups whose axial ranges touch
    stacks: list[list[CylGroup]] = []
    for gr in sorted(concave_full, key=lambda x: x.radius):
        for st in stacks:
            base = st[0]
            if _same_line(ctx, base.origin, base.direction, gr.origin, gr.direction):
                b0, b1 = _axial_range(ctx, gr.faces, base.origin, base.direction)
                lo = min(x.a_min for x in st)
                hi = max(x.a_max for x in st)
                if b0 <= hi + ctx.tol.linear and b1 >= lo - ctx.tol.linear and gr.radius > base.radius:
                    st.append(gr)
                    break
        else:
            stacks.append([gr])

    for st in stacks:
        bore = st[0]  # smallest radius = main bore
        # express everything in the bore's axis frame
        o, d = bore.origin, bore.direction
        ranges = [_axial_range(ctx, gr.faces, o, d) for gr in st]
        cones = _coaxial_cones(ctx, bore, concave=True)
        cone_ranges = [_axial_range(ctx, [c], o, d) for c in cones]
        lo = min([r[0] for r in ranges] + [r[0] for r in cone_ranges])
        hi = max([r[1] for r in ranges] + [r[1] for r in cone_ranges])
        open_lo, open_hi = _is_open(ctx, bore, lo, -1.0), _is_open(ctx, bore, hi, +1.0)
        through = open_lo and open_hi

        bore_lo, bore_hi = ranges[0]
        counterbore = None
        countersink = None
        kind = HoleKind.SIMPLE
        entry_at_hi: bool
        notes: list[str] = []
        if len(st) > 1:
            cb = st[1]
            cb_lo, cb_hi = ranges[1]
            counterbore = Counterbore(diameter=2 * cb.radius, depth=cb_hi - cb_lo)
            kind = HoleKind.COUNTERBORE
            entry_at_hi = cb_hi >= bore_hi - ctx.tol.linear
            if len(st) > 2:
                notes.append(f"{len(st) - 2} additional coaxial bore step(s) not described")
        else:
            entry_at_hi = open_hi if open_hi != open_lo else True
        cone_used: list[int] = []
        for c, (c0, c1) in zip(cones, cone_ranges):
            at_hi = abs(c0 - bore_hi) < ctx.tol.linear or c0 >= bore_hi - ctx.tol.linear
            at_lo = abs(c1 - bore_lo) < ctx.tol.linear or c1 <= bore_lo + ctx.tol.linear
            r_min, r_max = _cone_radii(ctx, c)
            if (at_hi and open_hi) or (at_lo and open_lo):
                if countersink is None and kind == HoleKind.SIMPLE:
                    countersink = Countersink(
                        diameter=2 * r_max, angle_deg=2 * abs(ctx.faces[c].half_angle_deg or 0.0)
                    )
                    kind = HoleKind.COUNTERSINK
                    entry_at_hi = at_hi
                    cone_used.append(c)
            elif not through:
                notes.append("conical bottom (drill point) present; depth excludes the point")
                cone_used.append(c)

        # direction into material from the entry end
        if entry_at_hi:
            entry_a, direction = hi, g.scale(d, -1.0)
        else:
            entry_a, direction = lo, d
        # THRU: material length along the axis; blind: length of the main bore
        depth = hi - lo if through else bore_hi - bore_lo
        face_idx = sorted({f for gr in st for f in gr.faces} | set(cone_used))
        # blind hole floor: planar neighbour perpendicular to the axis at the closed end
        if not through:
            for f in list(face_idx):
                for nb in ctx.topo.adjacent_faces(f):
                    fi = ctx.faces[nb]
                    if fi.surface_type == SurfaceType.PLANE and g.parallel(fi.normal, d, ctx.tol.angular_deg):
                        a = g.project_on_axis(fi.centroid, o, d)
                        closed_a = lo if entry_at_hi else hi
                        if abs(a - closed_a) < ctx.tol.linear and g.point_line_distance(fi.centroid, o, d) < ctx.tol.linear:
                            face_idx.append(nb)
            face_idx = sorted(set(face_idx))
        edge_idx = sorted(
            {
                e
                for f in face_idx
                for e in ctx.topo.face_edges[f]
                if ctx.edges[e].circle_radius is not None
            }
        )
        ctx.claimed_faces.update(face_idx)
        confidence = 0.99 if kind == HoleKind.SIMPLE and (through or open_lo or open_hi) else 0.95
        if not (open_lo or open_hi):
            notes.append("neither end opens to air: internal cylindrical void")
            confidence = 0.5
        holes.append(
            HoleFeature(
                id=ids.feature_id("HOLE", ctx.signatures(face_idx)),
                kind=kind,
                diameter=2 * bore.radius,
                axis=Axis(origin=bore.point_at(entry_a), direction=direction),
                depth=depth,
                through=through,
                counterbore=counterbore,
                countersink=countersink,
                confidence=confidence,
                face_ids=ctx.ids(face_idx),
                edge_ids=ctx.eids(edge_idx),
                provenance=Provenance(method="concave_cylinder_stack+axial_probe", exact=True),
                notes=notes,
            )
        )
    return holes


def recognize_bosses(ctx: RecognitionContext, groups: list[CylGroup]) -> list[BossFeature]:
    bosses: list[BossFeature] = []
    for gr in groups:
        if gr.concave or not gr.full:
            continue
        o, d = gr.origin, gr.direction
        # base end = end whose circular edge is concave (meets a larger face); else the low end
        base_at_hi = False
        for f in gr.faces:
            for e in ctx.topo.face_edges[f]:
                ei = ctx.edges[e]
                if ei.circle_center is None or ctx.convexity[e] != Convexity.CONCAVE:
                    continue
                a = g.project_on_axis(ei.circle_center, o, d)
                if abs(a - gr.a_max) < ctx.tol.linear:
                    base_at_hi = True
        base_a = gr.a_max if base_at_hi else gr.a_min
        direction = g.scale(d, -1.0) if base_at_hi else d
        ctx.claimed_faces.update(gr.faces)
        bosses.append(
            BossFeature(
                id=ids.feature_id("BOSS", ctx.signatures(gr.faces)),
                diameter=2 * gr.radius,
                axis=Axis(origin=gr.point_at(base_a), direction=direction),
                height=gr.a_max - gr.a_min,
                confidence=0.9,
                face_ids=ctx.ids(gr.faces),
                provenance=Provenance(method="convex_full_cylinder", exact=True),
                notes=["external cylindrical feature (boss, shaft step or outer diameter)"],
            )
        )
    return bosses
