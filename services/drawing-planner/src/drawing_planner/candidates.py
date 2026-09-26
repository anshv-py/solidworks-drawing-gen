"""Deterministic dimension-candidate engine.

Every ``value`` is copied from a GeometryIR field (named in ``source``). Nothing is
estimated, rounded into a different value, or invented; rounding happens only in
the printed ``text`` according to the plan's decimal places.
"""

from __future__ import annotations

import math
from collections import defaultdict

from drawing_schema.candidates import CandidateKind, CandidateRole, DimensionCandidate, ViewRule
from geometry_schema import (
    BossFeature,
    ChamferFeature,
    CylinderSurface,
    ConeSurface,
    FeatureType,
    FilletFeature,
    GeometryIR,
    HoleFeature,
    HoleKind,
    PatternFeature,
    PatternType,
    PocketFeature,
    SlotFeature,
)

AXES: dict[str, tuple[float, float, float]] = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}
TOL = 1e-4

# priorities (lower = more important). They also decide which link of a
# redundant chain survives.
P_OVERALL, P_CALLOUT, P_DIAMETER, P_PCD, P_SIZE, P_PITCH, P_LOCATION, P_HEIGHT, P_DEPTH, P_RADIUS, P_CHAMFER = (
    0, 5, 10, 12, 15, 18, 20, 25, 30, 35, 36,
)


TRAILING_ZEROS = True  # module default; the builder passes the plan's preference explicitly


def _fmt(v: float, dp: int, trailing_zeros: bool | None = None) -> str:
    keep = TRAILING_ZEROS if trailing_zeros is None else trailing_zeros
    s = f"{v:.{dp}f}"
    if s.startswith("-") and float(s) == 0:
        s = s[1:]
    if keep or "." not in s:
        return s
    return s.rstrip("0").rstrip(".")


def _prefix(n: int) -> str:
    return f"{n}X " if n > 1 else ""


def _axis_name(d) -> str | None:
    for name, a in AXES.items():
        if abs(abs(d[0] * a[0] + d[1] * a[1] + d[2] * a[2]) - 1.0) < 1e-6:
            return name
    return None


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _with(p, i, v):
    q = list(p)
    q[i] = v
    return tuple(q)


fmt = _fmt


def hole_text(h: HoleFeature, n: int, dp: int, equally_spaced: bool = False, thread=None,
              tz: bool | None = None) -> str:
    def fmt(v: float, d: int) -> str:  # noqa: F811 - bind the trailing-zero preference
        return _fmt(v, d, tz)

    if thread is not None:  # the thread designation replaces the drilled Ø
        depth = "THRU" if h.through else f"DEPTH {fmt(thread.depth, dp)}"
        t = f"{_prefix(n)}{thread.designation} {depth}"
        if not h.through and thread.depth is not None and thread.depth < h.depth - 1e-6:
            t += f"\nDRILL Ø{fmt(h.diameter, dp)} DEPTH {fmt(h.depth, dp)}"
    else:
        t = f"{_prefix(n)}Ø{fmt(h.diameter, dp)} " + ("THRU" if h.through else f"DEPTH {fmt(h.depth, dp)}")
    if h.counterbore:
        t += f"\nCBORE Ø{fmt(h.counterbore.diameter, dp)} DEPTH {fmt(h.counterbore.depth, dp)}"
    if h.countersink:
        t += f"\nCSK Ø{fmt(h.countersink.diameter, dp)} X {_fmt(h.countersink.angle_deg, 0, False)}°"
    if equally_spaced:
        t += " EQ SP"
    return t


def _hole_key(h: HoleFeature, threads: dict | None = None) -> tuple:
    r = lambda x: None if x is None else round(x, 4)  # noqa: E731
    return (
        r(h.diameter), h.kind.value, h.through, None if h.through else r(h.depth),
        (r(h.counterbore.diameter), r(h.counterbore.depth)) if h.counterbore else None,
        (r(h.countersink.diameter), r(h.countersink.angle_deg)) if h.countersink else None,
        _axis_name(h.axis.direction),
        (threads or {}).get(h.id).designation if (threads or {}).get(h.id) else None,
    )


class _Builder:
    def __init__(self, ir: GeometryIR, dp: int, trailing_zeros: bool = True, threads: dict | None = None) -> None:
        self.ir, self.dp = ir, dp
        self.tz = trailing_zeros
        self.threads = threads or {}
        self.out: list[DimensionCandidate] = []
        self.bmin, self.bmax = ir.bounding_box.min, ir.bounding_box.max
        self.faces = {f.id: f for f in ir.faces}
        self.bosses = [f for f in ir.features if f.type == FeatureType.BOSS]

    def f(self, v: float) -> str:
        return fmt(v, self.dp, self.tz)

    def add(self, **kw) -> None:
        self.out.append(DimensionCandidate(**kw))

    # ------------------------------------------------------------------ overall
    def overall(self) -> None:
        size = self.ir.bounding_box.size
        # a boss whose Ø spans the full extent across its axis replaces those overall dims
        replaced: set[str] = set()
        for b in self.bosses:
            ax = _axis_name(b.axis.direction)
            if ax is None:
                continue
            others = [a for a in AXES if a != ax]
            if all(abs(size[AXIS_INDEX[a]] - b.diameter) < TOL for a in others):
                replaced.update(others)
        for name, i in AXIS_INDEX.items():
            if name in replaced:
                continue
            p1 = self.bmin
            p2 = _with(self.bmin, i, self.bmax[i])
            self.add(
                id=f"DIM-OVERALL-{name}", kind=CandidateKind.LINEAR, role=CandidateRole.OVERALL,
                value=size[i], text=self.f(size[i]), source=f"bounding_box.size[{i}]",
                view_rule=ViewRule.IN_PLANE, priority=P_OVERALL, p1=p1, p2=p2, direction=AXES[name],
            )

    # ------------------------------------------------------------------ holes
    def _on_boss_axis(self, h: HoleFeature) -> bool:
        for b in self.bosses:
            d = b.axis.direction
            if abs(abs(sum(x * y for x, y in zip(d, h.axis.direction))) - 1.0) > 1e-6:
                continue
            v = [h.axis.origin[k] - b.axis.origin[k] for k in range(3)]
            along = sum(v[k] * d[k] for k in range(3))
            perp = math.sqrt(max(0.0, sum(c * c for c in v) - along * along))
            if perp < TOL:
                return True
        return False

    def _locate(self, h_center, axis_dir, fid: str, tag: str, feature_ids: list[str],
                target: str | None = None) -> None:
        """Baseline location from the part's min faces. ``target`` = anchor kind of the located point."""
        ax = _axis_name(axis_dir)
        names = [n for n in AXES if n != ax]
        if ax is None:
            # an axis on an angled face: its entry point lies on that face (2 degrees of freedom) - locate it
            # along the two principal axes most square to the axis; the third follows from the face
            names = sorted(AXES, key=lambda n: (round(abs(sum(a * b for a, b in zip(AXES[n], axis_dir))), 9), n))[:2]
        for name in names:
            i = AXIS_INDEX[name]
            value = h_center[i] - self.bmin[i]
            if value < TOL:
                continue
            self.add(
                id=f"DIM-LOC-{tag}-{name}", kind=CandidateKind.LINEAR, role=CandidateRole.LOCATION,
                value=value, text=self.f(value),
                source=f"{fid}.center[{i}] - bounding_box.min[{i}]",
                view_rule=ViewRule.IN_PLANE, priority=P_LOCATION,
                p1=_with(h_center, i, self.bmin[i]), p2=tuple(h_center), direction=AXES[name],
                feature_ids=feature_ids, anchors=("FACE", target or f"CENTER:{tag}"),
            )

    def holes(self) -> None:
        holes = {f.id: f for f in self.ir.features if f.type == FeatureType.HOLE}
        patterns = [f for f in self.ir.features if f.type == FeatureType.PATTERN and f.member_type == FeatureType.HOLE]
        in_pattern: set[str] = set()
        for p in patterns:
            members = [holes[m] for m in p.member_feature_ids if m in holes]
            if not members:
                continue
            in_pattern.update(m.id for m in members)
            self._pattern(p, members)
        groups: dict[tuple, list[HoleFeature]] = defaultdict(list)
        for h in holes.values():
            if h.id not in in_pattern:
                groups[_hole_key(h, self.threads)].append(h)
        for members in groups.values():
            members.sort(key=lambda h: h.id)
            ref = members[0]
            self._callout(ref, members, hole_text(ref, len(members), self.dp, thread=self.threads.get(ref.id), tz=self.tz))
            for h in members:
                if not self._on_boss_axis(h):
                    self._locate(h.axis.origin, h.axis.direction, h.id, h.id, [h.id])

    def _callout(self, ref: HoleFeature, members, text: str, pattern_id: str | None = None) -> None:
        self.add(
            id=f"DIM-CALLOUT-{pattern_id or ref.id}", kind=CandidateKind.HOLE_CALLOUT, role=CandidateRole.CALLOUT,
            value=ref.diameter, text=text, source=f"{ref.id}.diameter/depth/through",
            view_rule=ViewRule.ALONG_AXIS, priority=P_CALLOUT, center=ref.axis.origin, axis=ref.axis.direction,
            radius=ref.diameter / 2, count=len(members), feature_ids=[m.id for m in members] + ([pattern_id] if pattern_id else []),
        )

    def _pattern(self, p: PatternFeature, members: list[HoleFeature]) -> None:
        members = sorted(members, key=lambda h: h.id)
        full_circle = p.pattern_type == PatternType.CIRCULAR and not p.notes
        ref = min(members, key=lambda h: tuple(round(c, 4) for c in h.axis.origin))
        self._callout(ref, members, hole_text(ref, len(members), self.dp, equally_spaced=full_circle,
                                              thread=self.threads.get(ref.id), tz=self.tz), p.id)
        ids = [p.id] + [m.id for m in members]
        if p.pattern_type == PatternType.CIRCULAR:
            self.add(
                id=f"DIM-PCD-{p.id}", kind=CandidateKind.PCD, role=CandidateRole.SIZE,
                value=p.pitch_circle_diameter, text=f"Ø{self.f(p.pitch_circle_diameter)}",
                source=f"{p.id}.pitch_circle_diameter", view_rule=ViewRule.ALONG_AXIS, priority=P_PCD,
                center=p.center, axis=p.axis_direction, radius=p.pitch_circle_diameter / 2, feature_ids=ids,
            )
            centre_on_axis = self._on_boss_axis(
                HoleFeature.model_construct(axis=type(ref.axis)(origin=p.center, direction=p.axis_direction))
            ) or any(
                h.id not in {m.id for m in members}
                and all(abs(a - b) < TOL for a, b in zip(h.axis.origin, p.center))
                for h in self.ir.features if h.type == FeatureType.HOLE
            )
            if not centre_on_axis:
                self._locate(p.center, p.axis_direction, p.id, p.id, ids)
            return
        # linear / rectangular: locate the reference member, dimension the pitches
        self._locate(ref.axis.origin, ref.axis.direction, ref.id, p.id, ids)
        for k, (d, pitch, n) in enumerate(zip(p.directions, p.pitches, p.counts)):
            if n < 2:
                continue
            p2 = _add(ref.axis.origin, _scale(d, pitch))
            label = f"{n - 1}X {self.f(pitch)}" if n > 2 else self.f(pitch)
            self.add(
                id=f"DIM-PITCH-{p.id}-{k}", kind=CandidateKind.LINEAR, role=CandidateRole.PITCH,
                value=pitch, text=label, source=f"{p.id}.pitches[{k}]", view_rule=ViewRule.IN_PLANE,
                priority=P_PITCH, p1=ref.axis.origin, p2=p2, direction=tuple(d), feature_ids=ids,
                anchors=(f"CENTER:{p.id}", f"CENTER:{p.id}"),
            )

    # ------------------------------------------------------------------ bosses
    def _end_chamfers(self, b: BossFeature) -> list[ChamferFeature]:
        """Conical chamfers that finish this boss's cylinder (they belong to the step length)."""
        faces = set(b.face_ids)
        return [
            c for c in self.ir.features
            if c.type == FeatureType.CHAMFER and faces & set(c.adjacent_face_ids)
            and isinstance(self.faces[c.face_ids[0]].surface, ConeSurface)
        ]

    def bosses_(self) -> None:
        for b in self.bosses:
            b: BossFeature
            mid = _add(b.axis.origin, _scale(b.axis.direction, b.height / 2))
            self.add(
                id=f"DIM-DIA-{b.id}", kind=CandidateKind.DIAMETER, role=CandidateRole.SIZE,
                value=b.diameter, text=f"Ø{self.f(b.diameter)}", source=f"{b.id}.diameter",
                view_rule=ViewRule.ACROSS_AXIS, priority=P_DIAMETER, center=mid, axis=b.axis.direction,
                radius=b.diameter / 2, feature_ids=[b.id],
            )
            # step length = cylinder length + the axial legs of chamfers at its ends
            p1, p2 = b.axis.origin, _add(b.axis.origin, _scale(b.axis.direction, b.height))
            length, source = b.height, f"{b.id}.height"
            for ch in self._end_chamfers(b):
                cone_c = self.faces[ch.face_ids[0]].centroid
                t = sum((cone_c[k] - b.axis.origin[k]) * b.axis.direction[k] for k in range(3))
                if t > b.height / 2:
                    p2 = _add(p2, _scale(b.axis.direction, ch.distance_1))
                else:
                    p1 = _add(p1, _scale(b.axis.direction, -ch.distance_1))
                length += ch.distance_1
                source += f" + {ch.id}.distance_1"
            self.add(
                id=f"DIM-HEIGHT-{b.id}", kind=CandidateKind.LINEAR, role=CandidateRole.SIZE,
                value=length, text=self.f(length), source=source,
                view_rule=ViewRule.IN_PLANE, priority=P_HEIGHT, p1=p1, p2=p2, direction=b.axis.direction,
                feature_ids=[b.id],
            )

    # ------------------------------------------------------------------ pockets / slots
    def pockets(self) -> None:
        for pk in [f for f in self.ir.features if f.type == FeatureType.POCKET]:
            pk: PocketFeature
            u = pk.length_direction
            n = pk.floor_normal
            v = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])
            for tag, d, size in (("L", u, pk.length), ("W", v, pk.width)):
                self.add(
                    id=f"DIM-{tag}-{pk.id}", kind=CandidateKind.LINEAR, role=CandidateRole.SIZE, value=size,
                    text=self.f(size), source=f"{pk.id}.{'length' if tag == 'L' else 'width'}",
                    view_rule=ViewRule.IN_PLANE, priority=P_SIZE,
                    p1=_add(pk.center, _scale(d, -size / 2)), p2=_add(pk.center, _scale(d, size / 2)),
                    direction=d, feature_ids=[pk.id],
                )
            top = _add(pk.center, _scale(n, pk.depth))
            self.add(
                id=f"DIM-DEPTH-{pk.id}", kind=CandidateKind.LINEAR, role=CandidateRole.DEPTH, value=pk.depth,
                text=self.f(pk.depth), source=f"{pk.id}.depth", view_rule=ViewRule.IN_PLANE,
                priority=P_DEPTH, p1=pk.center, p2=top, direction=n, feature_ids=[pk.id],
            )
            # locate the pocket's near edges from the part edges
            corner = _add(_add(pk.center, _scale(u, -pk.length / 2)), _scale(v, -pk.width / 2))
            self._locate(corner, n, pk.id, pk.id, [pk.id], target="FACE")

    def grooves(self) -> None:
        """Face groove (O-ring gland): outer and inner Ø where the walls show side-on, and its depth."""
        for gv in [f for f in self.ir.features if f.type == FeatureType.GROOVE]:
            d = gv.axis.direction
            mid = _add(gv.axis.origin, _scale(d, gv.depth / 2))
            for tag, dia in (("OD", gv.outer_diameter), ("ID", gv.inner_diameter)):
                self.add(
                    id=f"DIM-G{tag}-{gv.id}", kind=CandidateKind.DIAMETER, role=CandidateRole.SIZE, value=dia,
                    text=f"Ø{self.f(dia)}", source=f"{gv.id}.{'outer' if tag == 'OD' else 'inner'}_diameter",
                    view_rule=ViewRule.ACROSS_AXIS, priority=P_DIAMETER, center=mid, axis=d, radius=dia / 2,
                    feature_ids=[gv.id],
                )
            # on the outer wall, along the first principal direction square to the axis
            k = next(i for i in range(3) if abs(d[i]) < 0.5)
            perp = tuple(1.0 if i == k else 0.0 for i in range(3))
            p1 = _add(gv.axis.origin, _scale(perp, gv.outer_diameter / 2))
            self.add(
                id=f"DIM-DEPTH-{gv.id}", kind=CandidateKind.LINEAR, role=CandidateRole.DEPTH, value=gv.depth,
                text=self.f(gv.depth), source=f"{gv.id}.depth", view_rule=ViewRule.IN_PLANE, priority=P_DEPTH,
                p1=p1, p2=_add(p1, _scale(d, gv.depth)), direction=d, feature_ids=[gv.id],
            )

    def slots(self) -> None:
        for s in [f for f in self.ir.features if f.type == FeatureType.SLOT]:
            s: SlotFeature
            u, n = s.length_direction, s.depth_direction
            v = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])
            for tag, d, size, src in (("L", u, s.length, "length"), ("W", v, s.width, "width")):
                self.add(
                    id=f"DIM-{tag}-{s.id}", kind=CandidateKind.LINEAR, role=CandidateRole.SIZE, value=size,
                    text=self.f(size), source=f"{s.id}.{src}", view_rule=ViewRule.IN_PLANE,
                    priority=P_SIZE, p1=_add(s.center, _scale(d, -size / 2)), p2=_add(s.center, _scale(d, size / 2)),
                    direction=d, feature_ids=[s.id],
                )
            self._locate(s.center, n, s.id, s.id, [s.id])

    # ------------------------------------------------------------------ blends
    def fillets(self) -> None:
        groups: dict[tuple, list[FilletFeature]] = defaultdict(list)
        for f in [f for f in self.ir.features if f.type == FeatureType.FILLET]:
            surf = self.faces[f.face_ids[0]].surface
            if not isinstance(surf, CylinderSurface):
                continue  # torus blends: not dimensioned yet
            key = (round(f.radius, 4), f.concave, _axis_name(surf.axis.direction))
            groups[key].append(f)
        for members in groups.values():
            members.sort(key=lambda f: f.id)
            ref = members[0]
            face = self.faces[ref.face_ids[0]]
            surf = face.surface
            self.add(
                id=f"DIM-R-{ref.id}", kind=CandidateKind.RADIUS, role=CandidateRole.SIZE, value=ref.radius,
                text=f"{_prefix(len(members))}R{self.f(ref.radius)}", source=f"{ref.id}.radius",
                view_rule=ViewRule.ALONG_AXIS, priority=P_RADIUS, center=surf.axis.origin,
                axis=surf.axis.direction, radius=ref.radius, anchor=face.centroid, count=len(members),
                feature_ids=[m.id for m in members],
            )

    def bends(self) -> None:
        """Sheet-metal bends: inside radius and angle, on the arc where the bend axis is seen end-on."""
        for b in sorted((f for f in self.ir.features if f.type == FeatureType.BEND), key=lambda f: f.id):
            face = self.faces[b.inner_face_ids[0]]
            surf = face.surface
            self.add(
                id=f"DIM-BEND-{b.id}", kind=CandidateKind.RADIUS, role=CandidateRole.SIZE, value=b.inner_radius,
                text=f"BEND R{self.f(b.inner_radius)} {_fmt(b.angle_deg, 0, False)}°", source=f"{b.id}.inner_radius",
                view_rule=ViewRule.ALONG_AXIS, priority=P_RADIUS, center=surf.axis.origin, axis=surf.axis.direction,
                radius=b.inner_radius, anchor=face.centroid, feature_ids=[b.id],
            )

    def chamfers(self) -> None:
        groups: dict[tuple, list[ChamferFeature]] = defaultdict(list)
        for c in [f for f in self.ir.features if f.type == FeatureType.CHAMFER]:
            surf = self.faces[c.face_ids[0]].surface
            key = (round(c.distance_1, 4), round(c.distance_2, 4), round(c.angle_deg, 3), surf.kind)
            groups[key].append(c)
        for members in groups.values():
            members.sort(key=lambda c: c.id)
            c = members[0]
            face = self.faces[c.face_ids[0]]
            d1, d2 = c.distance_1, c.distance_2
            label = (
                f"{self.f(d1)} X {fmt(c.angle_deg, 0, False)}°" if abs(d1 - d2) < TOL
                else f"{self.f(d1)} X {self.f(d2)}"
            )
            common = dict(
                id=f"DIM-CH-{c.id}", kind=CandidateKind.CHAMFER, role=CandidateRole.SIZE, value=d1,
                text=f"{_prefix(len(members))}{label}", source=f"{c.id}.distance_1/distance_2/angle_deg",
                priority=P_CHAMFER, count=len(members), feature_ids=[m.id for m in members],
            )
            if isinstance(face.surface, ConeSurface):
                # conical chamfer: seen from the side; anchor on the cone at mid radius
                cyl_r = max(
                    (self.faces[a].surface.radius for a in c.adjacent_face_ids
                     if isinstance(self.faces[a].surface, CylinderSurface)),
                    default=None,
                )
                if cyl_r is None:
                    continue
                self.add(view_rule=ViewRule.ACROSS_AXIS, center=face.centroid, axis=face.surface.axis.direction,
                         radius=cyl_r - d2 / 2, **common)
            else:
                na = self.faces[c.adjacent_face_ids[0]].surface.normal
                nb = self.faces[c.adjacent_face_ids[1]].surface.normal
                edge = (na[1] * nb[2] - na[2] * nb[1], na[2] * nb[0] - na[0] * nb[2], na[0] * nb[1] - na[1] * nb[0])
                ln = math.sqrt(sum(x * x for x in edge))
                self.add(view_rule=ViewRule.ALONG_AXIS, axis=tuple(x / ln for x in edge), anchor=face.centroid,
                         **common)


def generate_candidates(ir: GeometryIR, decimal_places: int = 2, trailing_zeros: bool = True,
                        threads: list | None = None) -> list[DimensionCandidate]:
    b = _Builder(ir, decimal_places, trailing_zeros, {t.feature_id: t for t in threads or []})
    b.overall()
    b.holes()
    b.bosses_()
    b.pockets()
    b.grooves()
    b.slots()
    b.fillets()
    b.bends()
    b.chamfers()
    seen: dict[str, DimensionCandidate] = {}
    for c in b.out:  # identical ids (e.g. two holes sharing a location) keep the first
        seen.setdefault(c.id, c)
    return sorted(seen.values(), key=lambda c: (c.priority, c.id))
