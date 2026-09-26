"""Functional role inference (primary rule set, RULES 4.1 / EX 7 pattern library).

Geometry cannot prove what a feature is for, so every inferred role is an *assumption*: it carries a
confidence and the reasons behind it, and is listed in the compliance report as "assumed role: X -
confirm or override". User roles (DrawingSettings.feature_roles) replace the guess for that face /
feature id; the ids are deterministic, so an override survives regeneration.

Signals used (all from GeometryIR, plus the user's thread callouts):
- part family: a turned body (main diameter on the envelope axis) is a SHAFT when its length is at least
  ``length_to_diameter_ge`` times the diameter, otherwise a DISC; everything else is PRISMATIC
- mounting face: the largest planar face on the envelope (prismatic), the largest face perpendicular to
  the axis (disc)
- bearing bore: a single large bore, clearly larger than the part's other holes, square to the mounting
  face; a counterbore step (shoulder + bore) raises the confidence
- central bore: a through hole on a disc's axis
- bearing seat / shoulder: shaft journals that end against a larger diameter, and the face between them
- clearance holes: holes whose diameter is an ISO 273 clearance size, or an unmatched through-hole pattern
- dowel holes: at most two holes of a standard pin diameter, deep enough to hold a pin
- tapped hole: a hole the user gave a thread callout
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from drawing_schema.pmi import Target, ThreadCallout
from drawing_schema.roles import FACE_ROLES, FeatureRole, RoleAssignment, RoleOverride, RoleSource
from geometry_schema import FeatureType, GeometryIR, SurfaceType

from drawing_planner.rule_set import RuleSet

_EPS = 1e-6


class PartFamily(StrEnum):
    PRISMATIC = "PRISMATIC"
    DISC = "DISC"
    SHAFT = "SHAFT"


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def main_turned_boss(ir: GeometryIR):
    """(boss, axis index) of a turned body's main diameter - a boss on the envelope's centre axis
    whose diameter spans the envelope - or (None, None)."""
    bb = ir.bounding_box
    ctr = [(bb.min[i] + bb.max[i]) / 2 for i in range(3)]
    for b in sorted((f for f in ir.features if f.type == FeatureType.BOSS), key=lambda b: (-b.diameter, b.id)):
        d = b.axis.direction
        k = max(range(3), key=lambda i: abs(d[i]))
        if abs(abs(d[k]) - 1) > _EPS:
            continue
        off = [ctr[i] - b.axis.origin[i] for i in range(3) if i != k]
        across = [bb.size[i] for i in range(3) if i != k]
        if math.hypot(*off) < 1e-3 and all(abs(s - b.diameter) < 1e-3 * max(1.0, b.diameter) for s in across):
            return b, k
    return None, None


def part_family(ir: GeometryIR, rules: RuleSet) -> PartFamily:
    boss, k = main_turned_boss(ir)
    if boss is None:
        return PartFamily.PRISMATIC
    ratio = rules.roles.inference.shaft.length_to_diameter_ge
    return PartFamily.SHAFT if ir.bounding_box.size[k] >= ratio * boss.diameter else PartFamily.DISC


@dataclass
class RoleResult:
    family: PartFamily
    assignments: list[RoleAssignment] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # invalid user overrides

    def by_ref(self) -> dict[str, RoleAssignment]:
        return {a.target.ref: a for a in self.assignments if a.role != FeatureRole.NONE}

    def of(self, role: FeatureRole) -> list[RoleAssignment]:
        return [a for a in self.assignments if a.role == role]


class _Inferer:
    def __init__(self, ir: GeometryIR, rules: RuleSet, threads: list[ThreadCallout]) -> None:
        self.ir, self.rules = ir, rules
        self.inf = rules.roles.inference
        self.features = {f.id: f for f in ir.features}
        self.faces = {f.id: f for f in ir.faces}
        self.planes = [f for f in ir.faces if f.surface_type == SurfaceType.PLANE]
        members = {m for f in ir.features if f.type == FeatureType.PATTERN for m in f.member_feature_ids}
        self.patterns = [f for f in ir.features if f.type == FeatureType.PATTERN and f.member_type == FeatureType.HOLE]
        self.single_holes = [f for f in ir.features if f.type == FeatureType.HOLE and f.id not in members]
        self.threads = {t.feature_id: t for t in threads}
        self.out: list[RoleAssignment] = []
        self.taken: set[str] = set()

    def add(self, target: Target, role: FeatureRole, confidence: float, description: str, reasons: list[str]) -> None:
        t = self.rules.treatment(role)
        self.out.append(RoleAssignment(target=target, role=role, source=RoleSource.INFERRED,
                                       confidence=round(confidence, 2), description=description, reasons=reasons,
                                       rule=t.rule if t else ""))
        self.taken.add(target.ref)

    # ------------------------------------------------------------------ helpers
    def hole_text(self, h) -> str:
        return f"Ø{h.diameter:.2f} {'THRU' if h.through else 'BLIND'} hole"

    def envelope_planes(self):
        bb = self.ir.bounding_box
        tol = 1e-4 * max(bb.size) + 1e-6
        out = []
        for f in self.planes:
            n = f.surface.normal
            k = max(range(3), key=lambda i: abs(n[i]))
            if abs(abs(n[k]) - 1) > _EPS:
                continue
            level = bb.min[k] if n[k] < 0 else bb.max[k]
            if abs(f.centroid[k] - level) < tol:
                out.append((f, k, n[k] < 0))
        return out

    def mounting_face_prismatic(self):
        env = self.envelope_planes()
        if not env:
            return None
        # largest area; a bounding-box minimum face wins a tie (the reference corner the part is dimensioned from)
        f, _, _ = max(env, key=lambda e: (round(e[0].area, 3), e[2], e[0].id))
        return f

    # ------------------------------------------------------------------ holes
    def holes(self, exclude: set[str]) -> None:
        cl = self.inf.clearance_holes
        dw = self.inf.dowel_holes
        for th_id, th in self.threads.items():
            h = self.features.get(th_id)
            if h is not None and th_id not in exclude:
                self.out.append(RoleAssignment(
                    target=Target(feature_id=th_id), role=FeatureRole.TAPPED_HOLE, source=RoleSource.USER,
                    confidence=1.0, description=f"{self.hole_text(h)} ({th.designation})",
                    reasons=[f"thread callout {th.designation} entered by the user"],
                    rule=self.rules.treatment(FeatureRole.TAPPED_HOLE).rule))
                self.taken.add(th_id)
        for p in sorted(self.patterns, key=lambda p: p.id):
            if p.id in exclude or p.id in self.taken or any(m in self.threads for m in p.member_feature_ids):
                continue
            h = self.features[p.member_feature_ids[0]]
            match = cl.match(h.diameter) if h.through else None  # a bolt passes through a clearance hole
            tap = None if match else self.tap_drill(h)
            if tap:
                self.add(Target(feature_id=p.id), FeatureRole.TAPPED_HOLE, tap[1],
                         f"{p.count}X {self.hole_text(h)} pattern", tap[0])
                continue
            if match:
                self.add(Target(feature_id=p.id), FeatureRole.CLEARANCE_HOLES, 0.8,
                         f"{p.count}X {self.hole_text(h)} pattern",
                         [f"Ø{h.diameter:g} is an ISO 273 clearance hole for {match[0]}",
                          f"{p.count} identical holes in a {p.pattern_type.value.lower()} pattern (bolt pattern)"])
            elif h.through:
                self.add(Target(feature_id=p.id), FeatureRole.CLEARANCE_HOLES, 0.4,
                         f"{p.count}X {self.hole_text(h)} pattern",
                         [f"{p.count} identical through holes in a pattern (likely a bolt pattern)",
                          f"Ø{h.diameter:g} is not an ISO 273 clearance size: the fastener is unknown, so the "
                          "position tolerance is not checked against it (hole MMC size - fastener size)"])
        singles = [h for h in self.single_holes if h.id not in exclude and h.id not in self.taken]
        by_dia: dict[float, list] = {}
        for h in singles:
            by_dia.setdefault(round(h.diameter, 3), []).append(h)
        for dia, group in sorted(by_dia.items()):
            match = cl.match(dia) if all(h.through for h in group) else None
            taps = [(h, self.tap_drill(h)) for h in group] if not match else []
            if taps and all(t for _, t in taps):
                for h, (reasons, conf) in sorted(taps, key=lambda x: x[0].id):
                    self.add(Target(feature_id=h.id), FeatureRole.TAPPED_HOLE, conf, self.hole_text(h), reasons)
                continue
            if match:
                for h in sorted(group, key=lambda h: h.id):
                    self.add(Target(feature_id=h.id), FeatureRole.CLEARANCE_HOLES, 0.6 if len(group) > 1 else 0.5,
                             self.hole_text(h),
                             [f"Ø{dia:g} is an ISO 273 clearance hole for {match[0]}"]
                             + ([f"{len(group)} holes of this size"] if len(group) > 1 else []))
                continue
            pin = any(abs(dia - d) < 0.01 for d in dw.diameters_mm)
            deep = all(h.depth >= h.diameter - 1e-6 for h in group)
            if pin and deep and len(group) <= dw.max_count:
                for h in sorted(group, key=lambda h: h.id):
                    self.add(Target(feature_id=h.id), FeatureRole.DOWEL_HOLE, 0.4, self.hole_text(h),
                             [f"Ø{dia:g} is a standard dowel-pin diameter (ISO 2338 / ISO 8734) and not a clearance "
                              "size", f"{len(group)} such hole(s), deep enough to hold a pin"])

    def tap_drill(self, h):
        """(reasons, confidence) when ``h`` is modelled at the tap drill of a coarse metric thread and is deep
        enough to engage it (STEP carries no threads: a tapped hole arrives as its drilled core)."""
        t = self.inf.tapped_holes
        m = t.match(h.diameter)
        if m is None or h.depth < t.min_engagement_ratio * m[1] - 1e-6:
            return None
        reasons = [f"Ø{h.diameter:g} is the tap drill of {m[0]}x{m[2]:g} (ISO 261 / ISO 2306)",
                   f"{'through' if h.through else 'blind'} hole {h.depth:g} deep (engagement >= "
                   f"{t.min_engagement_ratio:g} x {m[1]:g})"]
        return reasons, (0.45 if h.through else 0.6)

    def special(self) -> None:
        """Keyways (a pocket cut into a turned diameter) and O-ring face grooves (+ their sealing face)."""
        bosses = [b for b in self.ir.features if b.type == FeatureType.BOSS]
        for pk in sorted((f for f in self.ir.features if f.type == FeatureType.POCKET), key=lambda f: f.id):
            if pk.id in self.taken:
                continue
            for b in bosses:
                a = b.axis.direction
                if abs(_dot(pk.floor_normal, a)) > 1e-6 or abs(abs(_dot(pk.length_direction, a)) - 1) > 1e-6:
                    continue
                rel = [pk.center[i] - b.axis.origin[i] for i in range(3)]
                along = _dot(rel, a)
                radial = math.sqrt(max(0.0, _dot(rel, rel) - along * along))
                if radial < b.diameter / 2 and -1e-6 <= along <= b.height + 1e-6 and pk.width < b.diameter / 2:
                    self.add(Target(feature_id=pk.id), FeatureRole.KEYWAY, 0.7,
                             f"{pk.length:g} x {pk.width:g} x {pk.depth:g} key seat",
                             [f"flat-bottomed slot along the Ø{b.diameter:g} axis, cut into its surface (a key seat)"])
                    break
        for gv in sorted((f for f in self.ir.features if f.type == FeatureType.GROOVE), key=lambda f: f.id):
            self.add(Target(feature_id=gv.id), FeatureRole.SEAL_GROOVE, 0.6,
                     f"Ø{gv.inner_diameter:g}-Ø{gv.outer_diameter:g} x {gv.depth:g} face groove",
                     ["annular groove of rectangular section in a flat face - an O-ring gland"])
            # the face the groove opens into seals against the mating part (EX 6: datum A)
            level = gv.axis.origin
            faces = [f for f in self.planes if abs(abs(_dot(f.surface.normal, gv.axis.direction)) - 1) < 1e-6
                     and abs(_dot([f.centroid[i] - level[i] for i in range(3)], gv.axis.direction)) < 1e-4]
            if faces:
                face = max(faces, key=lambda f: (round(f.area, 3), f.id))
                self.out = [a for a in self.out if a.role != FeatureRole.MOUNTING_FACE and a.target.ref != face.id]
                self.add(Target(face_id=face.id), FeatureRole.SEALING_FACE, 0.6, f"planar face {face.id}",
                         [f"the face the Ø{gv.outer_diameter:g} O-ring groove opens into - it seals against the "
                          "mating part"])

    # ------------------------------------------------------------------ families
    def prismatic(self) -> None:
        mount = self.mounting_face_prismatic()
        if mount is not None:
            self.add(Target(face_id=mount.id), FeatureRole.MOUNTING_FACE, 0.6,
                     f"planar face {mount.id} ({mount.area:.0f} mm²)",
                     ["largest planar face on the part's envelope - the likely seating / fixturing face"])
        normal = mount.surface.normal if mount is not None else None
        bi = self.inf.bearing_bore
        bores = [h for h in self.single_holes if h.id not in self.threads and h.diameter >= bi.min_diameter_mm - _EPS
                 and (normal is None or abs(abs(_dot(h.axis.direction, normal)) - 1) < 1e-6)]
        if bores:
            bore = max(bores, key=lambda h: (h.diameter, h.id))
            others = [f.diameter for f in self.ir.features if f.type == FeatureType.HOLE and f.id != bore.id]
            if not others or bore.diameter >= bi.ratio_to_other_holes * max(others) - _EPS:
                reasons = [f"largest bore (Ø{bore.diameter:g}), square to the mounting face"]
                conf = 0.4
                if others:
                    reasons.append(f"at least {bi.ratio_to_other_holes:g}x the other holes (max Ø{max(others):g})")
                    conf += 0.1
                if bore.counterbore is not None:
                    reasons.append("stepped bore (shoulder + bore): a typical bearing seat")
                    conf += 0.2
                self.add(Target(feature_id=bore.id), FeatureRole.BEARING_BORE, conf, self.hole_text(bore), reasons)
        self.holes(set())

    def disc(self, boss, k: int) -> None:
        d = boss.axis.direction
        ends = [f for f in self.planes if abs(abs(_dot(f.surface.normal, d)) - 1) < _EPS]
        if ends:
            seat = max(ends, key=lambda f: (round(f.area, 3), f.id))
            self.add(Target(face_id=seat.id), FeatureRole.MOUNTING_FACE, 0.6,
                     f"planar face {seat.id} ({seat.area:.0f} mm²)",
                     ["largest face perpendicular to the part axis - the likely seating face"])
        on_axis = []
        for h in self.single_holes:
            if abs(abs(_dot(h.axis.direction, d)) - 1) > 1e-6 or h.id in self.threads:
                continue
            off = [h.axis.origin[i] - boss.axis.origin[i] for i in range(3) if i != k]
            if math.hypot(*off) < 1e-3 and h.through:
                on_axis.append(h)
        central = max(on_axis, key=lambda h: (h.diameter, h.id)) if on_axis else None
        if central is not None:
            self.add(Target(feature_id=central.id), FeatureRole.CENTRAL_BORE, 0.7, self.hole_text(central),
                     ["through bore on the part axis - the functional centre of the part"])
        self.holes({central.id} if central else set())

    def shaft(self, boss, k: int) -> None:
        d = boss.axis.direction
        axis = max(range(3), key=lambda i: abs(d[i]))
        bosses = [b for b in self.ir.features if b.type == FeatureType.BOSS
                  and abs(abs(_dot(b.axis.direction, d)) - 1) < _EPS
                  and math.dist([b.axis.origin[i] for i in range(3) if i != k],
                                [boss.axis.origin[i] for i in range(3) if i != k]) < 1e-3]

        def span(b) -> tuple[float, float]:
            a = b.axis.origin[axis]
            e = a + b.axis.direction[axis] * b.height
            return min(a, e), max(a, e)

        lo = min(span(b)[0] for b in bosses)
        hi = max(span(b)[1] for b in bosses)
        seats = []
        for b in bosses:
            s0, s1 = span(b)
            for other in bosses:
                if other.id == b.id or other.diameter <= b.diameter + _EPS:
                    continue
                o0, o1 = span(other)
                for at in (s0, s1):
                    if min(abs(at - o0), abs(at - o1)) < 1e-3:
                        seats.append((b, other, at, min(s0 - lo, hi - s1)))
        chosen: dict[str, tuple] = {}
        for b, other, at, end_gap in sorted(seats, key=lambda s: (s[3], -s[0].height, s[0].id)):
            if b.id not in chosen and len(chosen) < 2:
                chosen[b.id] = (b, other, at)
        for b, other, at in sorted(chosen.values(), key=lambda s: s[0].id):
            self.add(Target(feature_id=b.id), FeatureRole.BEARING_SEAT, 0.5, f"Ø{b.diameter:.2f} journal",
                     [f"journal ending against the larger Ø{other.diameter:g} (a bearing shoulder)"])
            shoulder = [f for f in self.planes if abs(abs(_dot(f.surface.normal, d)) - 1) < _EPS
                        and abs(f.centroid[axis] - at) < 1e-3]
            if shoulder:
                f = max(shoulder, key=lambda f: (round(f.area, 3), f.id))
                if f.id not in self.taken:
                    self.add(Target(face_id=f.id), FeatureRole.SHOULDER_FACE, 0.5, f"shoulder face {f.id}",
                             [f"face between the Ø{b.diameter:g} seat and the Ø{other.diameter:g} diameter "
                              "(locates the bearing axially)"])
        self.holes(set())


def _describe(ir: GeometryIR, t: Target) -> str:
    if t.face_id:
        return f"face {t.face_id}"
    f = next((f for f in ir.features if f.id == t.feature_id), None)
    return f"{f.type.value.lower()} {f.id}" if f else str(t.feature_id)


def _check_override(ir: GeometryIR, o: RoleOverride) -> str | None:
    feats = {f.id: f for f in ir.features}
    faces = {f.id: f for f in ir.faces}
    r = o.role
    if o.target.face_id is not None:
        face = faces.get(o.target.face_id)
        if face is None:
            return f"role {r.value}: face {o.target.face_id} does not exist on this part"
        if r != FeatureRole.NONE and r not in FACE_ROLES:
            return f"role {r.value} needs a hole / boss feature, not a face"
        if r != FeatureRole.NONE and face.surface_type != SurfaceType.PLANE:
            return f"role {r.value}: face {o.target.face_id} is not planar"
        return None
    f = feats.get(o.target.feature_id)
    if f is None:
        return f"role {r.value}: feature {o.target.feature_id} does not exist on this part"
    if r in FACE_ROLES:
        return f"role {r.value} needs a planar face, not a feature"
    if r == FeatureRole.BEARING_SEAT and f.type != FeatureType.BOSS:
        return f"role {r.value} needs a boss (journal)"
    if r in (FeatureRole.BEARING_BORE, FeatureRole.CENTRAL_BORE, FeatureRole.DOWEL_HOLE, FeatureRole.TAPPED_HOLE,
             FeatureRole.CLEARANCE_HOLES) and f.type not in (FeatureType.HOLE, FeatureType.PATTERN):
        return f"role {r.value} needs a hole or hole pattern"
    if r == FeatureRole.KEYWAY and f.type not in (FeatureType.POCKET, FeatureType.SLOT):
        return f"role {r.value} needs a pocket or slot"
    if r == FeatureRole.SEAL_GROOVE and f.type != FeatureType.GROOVE:
        return f"role {r.value} needs a groove"
    return None


def infer_roles(ir: GeometryIR, rules: RuleSet, overrides: list[RoleOverride] | None = None,
                threads: list[ThreadCallout] | None = None) -> RoleResult:
    """Inferred roles with the user's overrides applied (an override replaces the guess for its target)."""
    fam = part_family(ir, rules)
    inf = _Inferer(ir, rules, threads or [])
    boss, k = main_turned_boss(ir)
    if fam == PartFamily.SHAFT:
        inf.shaft(boss, k)
    elif fam == PartFamily.DISC:
        inf.disc(boss, k)
    else:
        inf.prismatic()
    inf.special()
    result = RoleResult(family=fam, assignments=inf.out)
    for o in overrides or []:
        err = _check_override(ir, o)
        if err:
            result.errors.append(err)
            continue
        t = rules.treatment(o.role)
        prev = next((a for a in result.assignments if a.target.ref == o.target.ref), None)
        user = RoleAssignment(
            target=o.target, role=o.role, source=RoleSource.USER, confidence=1.0,
            description=prev.description if prev else _describe(ir, o.target),
            reasons=["set by the user" if prev is None or prev.role != o.role else "confirmed by the user"],
            rule=t.rule if t else "")
        result.assignments = [a for a in result.assignments if a.target.ref != o.target.ref] + [user]
        if o.role in (FeatureRole.MOUNTING_FACE, FeatureRole.SEALING_FACE):
            # one primary face: the user's choice replaces an inferred one
            result.assignments = [a for a in result.assignments if not (
                a.source == RoleSource.INFERRED and a.role in (FeatureRole.MOUNTING_FACE, FeatureRole.SEALING_FACE))]
    result.assignments.sort(key=lambda a: (a.role.value, a.target.ref))
    return result


__all__ = ["PartFamily", "RoleResult", "infer_roles", "main_turned_boss", "part_family"]
