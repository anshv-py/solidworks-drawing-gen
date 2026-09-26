"""Default datums and GD&T, applied directly to the drawing (no suggestion step).

Conventions follow an external reference drawing generator (not in this repository): a prismatic part is
dimensioned from its bounding-box minimum corner, so the datum reference frame sits on those three
faces; a turned part is referenced to its main diameter's axis and a shoulder face. Every value
comes from the general tolerance these defaults declare - ISO 2768-mK - so nothing is guessed:

  ISO 2768-2 class K   flatness / straightness, perpendicularity, circular run-out
  ISO 2768-1 class m   linear tolerance t(L); a hole located by TEDs gets the positional zone that
                       circumscribes the ±t square it would have had: Ø 2·√2·t (rounded down)

Datum-feature rule 3 is enforced by construction: a datum feature's own control is always one
preferred step tighter than every tolerance that references it.

Applied only when the user supplied no datums or feature control frames of their own, and only
to targets the drawing can show (placed callouts / diameter dimensions, faces edge-on in a
selected orthographic view). Turn off with ``DrawingSettings.default_gdt = False``.

With functional roles (``drawing_planner.roles``) the primary rule set's treatments apply on top
(rules/drawing_rules.yaml, RULES 4 / EX 7): the datum reference frame follows RULES 4.1 (A = mounting /
sealing face, B = bearing or central bore, C = dowel hole), and bores, seats, clearance / dowel / tapped
holes get the rule set's fits, GD&T and surface finish. Features without a role keep the ISO 2768 values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from drawing_schema.candidates import CandidateKind, CandidateRole, DimensionCandidate
from drawing_schema.frames import Frame, dot
from drawing_schema.pmi import (
    NEEDS_DATUM,
    Datum,
    DatumReference,
    DimensionTolerance,
    FeatureControlFrame,
    FeatureNote,
    GdtCharacteristic as G,
    SurfaceFinishMark,
    Target,
    ToleranceKind,
)
from drawing_schema.roles import FeatureRole as R
from geometry_schema import FeatureType, GeometryIR, SurfaceType

from drawing_planner.iso286 import UnsupportedFit, deviations
from drawing_planner.roles import RoleResult, main_turned_boss
from drawing_planner.rule_set import FrameRule, RuleSet

DEFAULT_GENERAL_TOLERANCE = "ISO 2768-mK"

# ISO 2768-1 class m (fine-medium), permissible deviation ± by nominal length (upper bound, mm)
_LINEAR_M = [(6, 0.1), (30, 0.2), (120, 0.3), (400, 0.5), (1000, 0.8), (2000, 1.2), (4000, 2.0)]
# ISO 2768-2 class K
_FLAT_K = [(10, 0.05), (30, 0.1), (100, 0.2), (300, 0.4), (1000, 0.6), (3000, 0.8)]
_PERP_K = [(100, 0.4), (300, 0.6), (1000, 0.8), (3000, 1.0)]
RUNOUT_K = 0.2
PREFERRED = [0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0,
             2.5, 3.0, 4.0, 5.0]
ORIENTATION = {G.PERPENDICULARITY, G.PARALLELISM, G.ANGULARITY}
_EPS = 1e-6


def _table(rows: list[tuple[float, float]], length: float) -> float:
    return next((t for limit, t in rows if length <= limit + 1e-9), rows[-1][1])


def linear_m(length: float) -> float:
    return _table(_LINEAR_M, length)


def flatness_k(length: float) -> float:
    return _table(_FLAT_K, length)


def perpendicularity_k(length: float) -> float:
    return _table(_PERP_K, length)


def position_zone(locating_length: float) -> float:
    """Ø zone equivalent to ±t (ISO 2768-m) coordinate tolerancing, rounded down to 0.05."""
    return max(0.05, math.floor(2 * math.sqrt(2) * linear_m(locating_length) / 0.05 + 1e-9) * 0.05)


def tighter_than(limit: float) -> float:
    """Largest preferred value strictly below ``limit``."""
    below = [p for p in PREFERRED if p < limit - 1e-9]
    return below[-1] if below else PREFERRED[0]


@dataclass
class DefaultGdt:
    datums: list[Datum] = field(default_factory=list)
    frames: list[FeatureControlFrame] = field(default_factory=list)
    basic_dimensions: list[str] = field(default_factory=list)
    tolerances: list[DimensionTolerance] = field(default_factory=list)
    finish_marks: list[SurfaceFinishMark] = field(default_factory=list)
    feature_notes: list[FeatureNote] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.datums or self.frames)


class _Builder:
    def __init__(self, ir: GeometryIR, placed: list[DimensionCandidate], frames: list[Frame],
                 roles: RoleResult | None = None, rules: RuleSet | None = None,
                 toleranced: set[str] | None = None) -> None:
        self.ir = ir
        self.placed = placed
        self.frames = frames
        self.roles = roles.by_ref() if roles is not None and rules is not None else {}
        self.rules = rules
        self.toleranced = set(toleranced or ())  # candidates the user already toleranced
        self.features = {f.id: f for f in ir.features}
        self.edges = {e.id: e for e in ir.edges}
        self.planes = [f for f in ir.faces if f.surface_type == SurfaceType.PLANE]
        self.out = DefaultGdt()
        members = {m for f in ir.features if f.type == FeatureType.PATTERN for m in f.member_feature_ids}
        # holes to locate: patterns, and holes that are not a pattern member
        self.hole_targets = [f for f in ir.features if (f.type == FeatureType.PATTERN and
                                                        f.member_type == FeatureType.HOLE)
                             or (f.type == FeatureType.HOLE and f.id not in members)]

    # ------------------------------------------------------------------ what the drawing can show
    def _ids(self, fid: str) -> set[str]:
        f = self.features[fid]
        return {fid, *getattr(f, "member_feature_ids", [])}

    def has_callout(self, fid: str) -> bool:
        ids = self._ids(fid)
        return any(c.kind == CandidateKind.HOLE_CALLOUT and ids & set(c.feature_ids) for c in self.placed)

    def has_diameter(self, fid: str) -> bool:
        return any(c.id == f"DIM-DIA-{fid}" for c in self.placed)

    def edge_on(self, face) -> bool:
        return any(abs(dot(face.surface.normal, f.eye)) < _EPS for f in self.frames)

    def extent(self, face) -> float:
        """Largest in-plane extent of a planar face (ISO 2768-2 nominal length)."""
        pts = [p for eid in face.edge_ids if (e := self.edges.get(eid)) for p in (e.start, e.end)]
        if not pts:
            return math.sqrt(face.area)
        return max(max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3))

    def bbox_face(self, axis: int, at_min: bool):
        """Largest planar face lying on a bounding-box side (normal along ``axis``)."""
        bb = self.ir.bounding_box
        level = bb.min[axis] if at_min else bb.max[axis]
        tol = 1e-4 * max(bb.size) + 1e-6
        cands = [f for f in self.planes if abs(abs(f.surface.normal[axis]) - 1) < _EPS
                 and abs(f.centroid[axis] - level) < tol and self.edge_on(f)]
        return max(cands, key=lambda f: (round(f.area, 3), f.id)) if cands else None

    # ------------------------------------------------------------------ roles (primary rule set)
    def role(self, ref: str) -> R | None:
        a = self.roles.get(ref)
        if a is None and ref in self.features:
            # a pattern member carries its pattern's role and vice versa
            f = self.features[ref]
            for m in getattr(f, "member_feature_ids", []):
                if m in self.roles:
                    return self.roles[m].role
            for p in self.ir.features:
                if p.type == FeatureType.PATTERN and ref in p.member_feature_ids and p.id in self.roles:
                    return self.roles[p.id].role
        return a.role if a else None

    def with_role(self, role: R) -> list[str]:
        return sorted(ref for ref, a in self.roles.items() if a.role == role)

    def letters(self) -> list[str]:
        return [d.letter for d in self.out.datums]

    def own_letter(self, target: Target) -> str | None:
        return next((d.letter for d in self.out.datums if d.target == target), None)

    def callout_of(self, fid: str) -> DimensionCandidate | None:
        ids = self._ids(fid)
        return next((c for c in sorted(self.placed, key=lambda c: c.id)
                     if c.kind == CandidateKind.HOLE_CALLOUT and ids & set(c.feature_ids)), None)

    def diameter_of(self, fid: str) -> DimensionCandidate | None:
        return next((c for c in self.placed if c.id == f"DIM-DIA-{fid}"), None)

    def rule_frames(self, role: R, target: Target, size: float, cap: float | None = None) -> None:
        """The treatment's frames for ``target``: datum references limited to the datums defined so
        far (never the target's own), ISO_2768_K values sized by ``size``, zones capped by ``cap``."""
        t = self.rules.treatment(role) if self.rules else None
        if t is None:
            return
        own = self.own_letter(target)
        for fr in t.frames:
            refs = "".join(x for x in fr.datums if x in self.letters() and x != own)
            if fr.characteristic in NEEDS_DATUM and not refs:
                continue  # e.g. the run-out of the seat that *is* datum A
            tol = self.k_value(fr, size) if fr.tolerance == "ISO_2768_K" else float(fr.tolerance)
            if fr.cap == "FLOATING_FASTENER" and cap is not None:
                tol = min(tol, cap)
            self.out.frames.append(FeatureControlFrame(
                characteristic=fr.characteristic, tolerance=round(tol, 3), diameter_zone=fr.diameter_zone,
                material_condition=fr.material_condition, target=target,
                datums=[DatumReference(letter=r) for r in refs]))

    @staticmethod
    def k_value(fr: FrameRule, size: float) -> float:
        if fr.characteristic in (G.FLATNESS, G.STRAIGHTNESS):
            return flatness_k(size)
        return perpendicularity_k(size)

    def rule_extras(self, role: R, target: Target, cand: DimensionCandidate | None) -> None:
        """Fit / size tolerance on the feature's dimension, surface finish and note of the treatment."""
        t = self.rules.treatment(role) if self.rules else None
        if t is None:
            return
        if cand is not None and cand.id not in self.toleranced:
            if t.fit:
                try:
                    up, lo = deviations(cand.value, t.fit)
                    self.out.tolerances.append(DimensionTolerance(
                        candidate_id=cand.id, kind=ToleranceKind.FIT, fit=t.fit, upper=up, lower=lo))
                    self.toleranced.add(cand.id)
                except UnsupportedFit as exc:
                    self.out.uncertainties.append(f"{role.value} {target.ref}: fit {t.fit} not applied ({exc})")
            elif t.size_tolerance:
                self.out.tolerances.append(DimensionTolerance(
                    candidate_id=cand.id, kind=ToleranceKind.DEVIATION,
                    upper=t.size_tolerance.upper, lower=t.size_tolerance.lower))
                self.toleranced.add(cand.id)
        if t.depth_tolerance:
            dc = next((c for c in self.placed if c.id == f"DIM-DEPTH-{target.ref}"), None)
            if dc is not None and dc.id not in self.toleranced:
                self.out.tolerances.append(DimensionTolerance(
                    candidate_id=dc.id, kind=ToleranceKind.DEVIATION,
                    upper=t.depth_tolerance.upper, lower=t.depth_tolerance.lower))
                self.toleranced.add(dc.id)
        if t.finish_ra:
            self.out.finish_marks.append(SurfaceFinishMark(target=target, ra_um=t.finish_ra))
        if t.note:
            self.out.feature_notes.append(FeatureNote(target=target, text=t.note))
        self.out.rationale.append(f"{target.ref} as {role.value} ({t.rule})")

    def fastener_cap(self, fid: str) -> float | None:
        """Floating-fastener limit H - F (hole MMC size minus fastener size) of an ISO 273 hole."""
        if self.rules is None:
            return None
        f = self.features[fid]
        h = self.features[f.member_feature_ids[0]] if f.type == FeatureType.PATTERN else f
        m = self.rules.roles.inference.clearance_holes.match(h.diameter)
        return None if m is None else max(0.05, math.floor((h.diameter - m[1]) / 0.05 + 1e-9) * 0.05)

    # ------------------------------------------------------------------ emitters
    def datum(self, letter: str, target: Target, why: str) -> None:
        self.out.datums.append(Datum(letter=letter, target=target))
        self.out.rationale.append(f"datum {letter} = {target.ref}: {why}")

    def frame(self, ch: G, tol: float, target: Target, refs: str = "", diameter: bool = False) -> None:
        self.out.frames.append(FeatureControlFrame(
            characteristic=ch, tolerance=round(tol, 3), diameter_zone=diameter, target=target,
            datums=[DatumReference(letter=r) for r in refs]))

    def position_holes(self, refs: str, locating_length) -> None:
        """One position frame per hole callout (a callout may cover several unpatterned holes). Holes
        with a role get the rule set's treatment; datum features (bores that are B, ...) are not located."""
        ted_ids: set[str] = set()
        for c in sorted((c for c in self.placed if c.kind == CandidateKind.HOLE_CALLOUT), key=lambda c: c.id):
            holes = [h for h in self.hole_targets if self._ids(h.id) & set(c.feature_ids)]
            if not holes:
                continue
            target = next((h for h in holes if h.type == FeatureType.PATTERN), min(holes, key=lambda h: h.id))
            tgt = Target(feature_id=target.id)
            role = self.role(target.id)
            if role in (R.BEARING_BORE, R.CENTRAL_BORE):
                continue  # datum / oriented features: their controls are emitted with the datum scheme
            if role in (R.CLEARANCE_HOLES, R.DOWEL_HOLE, R.TAPPED_HOLE):
                self.rule_frames(role, tgt, 0.0, cap=self.fastener_cap(target.id))
                self.rule_extras(role, tgt, c)
            else:
                zone = min(position_zone(locating_length(h)) for h in holes)
                self.frame(G.POSITION, zone, tgt, refs, diameter=True)
            for h in holes:
                ted_ids |= self._ids(h.id)
        for c in self.placed:
            if ted_ids & set(c.feature_ids) and (c.role in (CandidateRole.LOCATION, CandidateRole.PITCH)
                                                 or c.kind == CandidateKind.PCD):
                self.out.basic_dimensions.append(c.id)

    def special_roles(self) -> None:
        """Keyways (EX 3 F5: N9 width, depth +0.1/0, position to A) and O-ring grooves (EX 6 F2: depth
        +0.05/0, profile of a surface to A|B, Ra 1.6) - whatever the part family."""
        for role, size_cid in ((R.KEYWAY, "DIM-W-{}"), (R.SEAL_GROOVE, None)):
            for ref in self.with_role(role):
                t = Target(feature_id=ref)
                cand = next((c for c in self.placed if size_cid and c.id == size_cid.format(ref)), None)
                if not any(ref in c.feature_ids for c in self.placed):
                    continue  # not on the drawing
                self.rule_frames(role, t, 0.0)
                self.rule_extras(role, t, cand)

    def prune_unreferenced(self) -> None:
        """Rule 9: a datum no frame references is dropped, with the orientation control that only
        qualified it (a role treatment may reference fewer datums than the default scheme declared)."""
        used = {r.letter for f in self.out.frames for r in f.datums}
        for d in [d for d in self.out.datums if d.letter != "A" and d.letter not in used]:
            self.out.datums.remove(d)
            if d.target.face_id:
                self.out.frames = [f for f in self.out.frames if not (
                    f.target == d.target and f.characteristic in ORIENTATION)]
            self.out.rationale.append(f"datum {d.letter} dropped: nothing references it")

    def refine_datum_features(self) -> None:
        """Rule 3: each datum feature's own control tighter than everything referencing it."""
        self.prune_unreferenced()
        frames = self.out.frames
        for d in reversed(self.out.datums):
            refs = [f.tolerance for f in frames if any(r.letter == d.letter for r in f.datums)]
            if not refs:
                continue
            limit = min(refs)
            for i, f in enumerate(frames):
                own = f.target == d.target and (not f.datums or (f.characteristic in ORIENTATION and
                                                                 all(r.letter != d.letter for r in f.datums)))
                if own and f.tolerance >= limit - 1e-9:
                    frames[i] = f.model_copy(update={"tolerance": tighter_than(limit)})

    # ------------------------------------------------------------------ part families
    def main_boss(self):
        """The turned body's main diameter: a boss on the bounding-box centre axis enclosing the part."""
        return main_turned_boss(self.ir)

    def role_face(self, *roles: R):
        """The planar face with one of ``roles`` that a selected view shows edge-on."""
        for role in roles:
            for ref in self.with_role(role):
                face = next((f for f in self.planes if f.id == ref), None)
                if face is not None and self.edge_on(face):
                    return face, role
        return None, None

    def primary_face(self, fallback):
        """RULES 4.1 datum A: the (user / inferred) sealing or mounting face, else ``fallback``."""
        face, role = self.role_face(R.SEALING_FACE, R.MOUNTING_FACE)
        return (face, role) if face is not None else (fallback, None)

    def datum_a_face(self, face, role, why: str) -> None:
        t = Target(face_id=face.id)
        if role is not None:
            self.datum("A", t, f"{role.value.lower().replace('_', ' ')} (RULES 4.1)")
            self.rule_frames(role, t, self.extent(face))
            self.rule_extras(role, t, None)
        else:
            self.datum("A", t, why)
            self.frame(G.FLATNESS, flatness_k(self.extent(face)), t)

    def rotational(self, boss, k: int) -> None:
        bb = self.ir.bounding_box
        d = boss.axis.direction
        coaxial = [b for b in self.ir.features if b.type == FeatureType.BOSS
                   and abs(abs(dot(b.axis.direction, d)) - 1) < _EPS
                   and math.dist([b.axis.origin[i] for i in range(3) if i != k],
                                 [boss.axis.origin[i] for i in range(3) if i != k]) < 1e-3]
        ends = [f for f in self.planes if abs(abs(dot(f.surface.normal, d)) - 1) < _EPS and self.edge_on(f)]
        shoulder = max(ends, key=lambda f: (round(f.area, 3), f.id)) if ends else None
        axial = [f for f in self.hole_targets if self.has_callout(f.id)]

        shaft_ratio = self.rules.roles.inference.shaft.length_to_diameter_ge if self.rules else 1.5
        if bb.size[k] >= shaft_ratio * boss.diameter:  # shaft: the longest journal's axis is the primary datum
            journals = [b for b in coaxial if self.has_diameter(b.id)]
            if not journals:
                return
            seats = [b for b in journals if self.role(b.id) == R.BEARING_SEAT]
            if seats:
                self.shaft_seats(seats, journals)
                return
            a = max(journals, key=lambda b: (b.height, b.diameter, b.id))
            self.datum("A", Target(feature_id=a.id), f"Ø{a.diameter:g} journal - longest diameter on the part axis")
            if self.roles:
                self.role_holes()
            self.frame(G.STRAIGHTNESS, flatness_k(a.height), Target(feature_id=a.id), diameter=True)
            for b in journals:
                if b.id != a.id:
                    self.frame(G.CIRCULAR_RUNOUT, RUNOUT_K, Target(feature_id=b.id), "A")
            if shoulder is not None:
                self.frame(G.CIRCULAR_RUNOUT, RUNOUT_K, Target(face_id=shoulder.id), "A")
            self.refine_datum_features()
            return

        # disc / flange: seating face first, the main diameter's axis centres the part
        face_a, role_a = self.primary_face(shoulder)
        if face_a is None:
            return
        self.datum_a_face(face_a, role_a, "largest face perpendicular to the part axis (seating face)")
        central = next((self.features[r] for r in self.with_role(R.CENTRAL_BORE) if self.has_callout(r)), None)
        if central is not None:
            self.central_bore(central, [h for h in axial if h.id != central.id], d)
            return
        if self.has_diameter(boss.id):
            b_ref = Target(feature_id=boss.id)
            if axial:
                self.datum("B", b_ref, f"Ø{boss.diameter:g} main diameter - axis of the part")
            self.frame(G.PERPENDICULARITY, perpendicularity_k(boss.height), b_ref, "A", diameter=True)
            if axial:
                o = boss.axis.origin

                def radial(h) -> float:
                    pts = [self.features[m].axis.origin for m in getattr(h, "member_feature_ids", [])] or [
                        h.axis.origin]
                    out = 0.0
                    for c in pts:
                        t = dot([c[i] - o[i] for i in range(3)], d)
                        out = max(out, math.dist(c, [o[i] + t * d[i] for i in range(3)]))
                    return out

                self.position_holes("AB", radial)
        self.refine_datum_features()

    def shaft_seats(self, seats, journals) -> None:
        """EX 3: datum A on the (longest) bearing seat; the seats' cylindricity, run-out, fit and finish;
        the shoulders square to A; other journals run out to A (ISO 2768-K)."""
        a = max(seats, key=lambda b: (b.height, b.diameter, b.id))
        self.datum("A", Target(feature_id=a.id), f"Ø{a.diameter:g} bearing seat - the axis the part turns about "
                                                 "(EX 3 uses the common axis of both seats)")
        for b in sorted(seats, key=lambda b: b.id):
            t = Target(feature_id=b.id)
            self.rule_frames(R.BEARING_SEAT, t, b.height)
            self.rule_extras(R.BEARING_SEAT, t, self.diameter_of(b.id))
        for b in journals:
            if b not in seats:
                self.frame(G.CIRCULAR_RUNOUT, RUNOUT_K, Target(feature_id=b.id), "A")
        for ref in self.with_role(R.SHOULDER_FACE):
            face = next((f for f in self.planes if f.id == ref), None)
            if face is not None and self.edge_on(face):
                t = Target(face_id=face.id)
                self.rule_frames(R.SHOULDER_FACE, t, self.extent(face))
                self.rule_extras(R.SHOULDER_FACE, t, None)
        self.role_holes()
        self.refine_datum_features()

    def role_holes(self) -> None:
        """Holes with a role on a part whose datum scheme does not locate holes (shafts): the rule set's
        treatment against the datums there are, their locating dimensions as TEDs."""
        ted_ids: set[str] = set()
        for c in sorted((c for c in self.placed if c.kind == CandidateKind.HOLE_CALLOUT), key=lambda c: c.id):
            holes = [h for h in self.hole_targets if self._ids(h.id) & set(c.feature_ids)]
            if not holes:
                continue
            target = next((h for h in holes if h.type == FeatureType.PATTERN), min(holes, key=lambda h: h.id))
            role = self.role(target.id)
            if role not in (R.CLEARANCE_HOLES, R.DOWEL_HOLE, R.TAPPED_HOLE):
                continue
            tgt = Target(feature_id=target.id)
            n = len(self.out.frames)
            self.rule_frames(role, tgt, 0.0, cap=self.fastener_cap(target.id))
            self.rule_extras(role, tgt, c)
            if any(f.characteristic == G.POSITION for f in self.out.frames[n:]):
                for h in holes:
                    ted_ids |= self._ids(h.id)
        for c in self.placed:
            if ted_ids & set(c.feature_ids) and c.role in (CandidateRole.LOCATION, CandidateRole.PITCH):
                self.out.basic_dimensions.append(c.id)

    def central_bore(self, central, others, d) -> None:
        """EX 6: B = the central bore's axis (only when other holes are located from it)."""
        b_ref = Target(feature_id=central.id)
        if others:
            self.datum("B", b_ref, f"Ø{central.diameter:g} central bore - the part's functional centre (RULES 4.1)")
        self.rule_frames(R.CENTRAL_BORE, b_ref, 0.0)
        self.rule_extras(R.CENTRAL_BORE, b_ref, self.callout_of(central.id))
        if others:
            co = central.axis.origin

            def radial(h) -> float:
                pts = [self.features[m].axis.origin for m in getattr(h, "member_feature_ids", [])] or [h.axis.origin]
                out = 0.0
                for c in pts:
                    t = dot([c[i] - co[i] for i in range(3)], d)
                    out = max(out, math.dist(c, [co[i] + t * d[i] for i in range(3)]))
                return out

            self.position_holes("AB", radial)
        self.refine_datum_features()

    def bearing_bore(self, bore, sides, located) -> None:
        """EX 4: A = mounting face, B = bearing-bore axis, C = a dowel hole (else a side face square to A)."""
        b_ref = Target(feature_id=bore.id)
        others = [h for h in located if h.id != bore.id]
        if others:
            self.datum("B", b_ref, f"Ø{bore.diameter:g} bearing bore - what the part is aligned to (RULES 4.1)")
        self.rule_frames(R.BEARING_BORE, b_ref, 0.0)
        self.rule_extras(R.BEARING_BORE, b_ref, self.callout_of(bore.id))
        if others:
            dowel = next((self.features[r] for r in self.with_role(R.DOWEL_HOLE) if self.has_callout(r)), None)
            if dowel is not None and any(h.id != dowel.id for h in others):
                self.datum("C", Target(feature_id=dowel.id),
                           f"Ø{dowel.diameter:g} dowel hole - stops rotation about B (RULES 4.1)")
            elif len(sides) >= 2:
                _, face_c = sides[1]
                self.datum("C", Target(face_id=face_c.id), "side face square to A - stops rotation about B")
                self.frame(G.PERPENDICULARITY, perpendicularity_k(self.extent(face_c)), Target(face_id=face_c.id),
                           "A")
            o = bore.axis.origin

            def from_bore(h) -> float:
                pts = [self.features[m].axis.origin for m in getattr(h, "member_feature_ids", [])] or [h.axis.origin]
                return max(math.dist(p, o) for p in pts)

            self.position_holes("".join(self.letters()), from_bore)
        self.refine_datum_features()

    def prismatic(self) -> None:
        sides = [(i, f) for i in range(3) if (f := self.bbox_face(i, at_min=True)) is not None]
        if not sides:
            return
        sides.sort(key=lambda s: (-round(s[1].area, 3), s[1].id))
        face_a, role_a = self.primary_face(sides[0][1])
        axis_a = max(range(3), key=lambda i: abs(face_a.surface.normal[i]))
        sides = [(axis_a, face_a)] + [s for s in sides if s[0] != axis_a]
        located = [h for h in self.hole_targets if self.has_callout(h.id)]
        self.datum_a_face(face_a, role_a, "largest bounding-box reference face (seating face)")
        bore = next((self.features[r] for r in self.with_role(R.BEARING_BORE) if self.has_callout(r)), None)
        if bore is not None:
            self.bearing_bore(bore, sides, located)
            return
        if not located or len(sides) < 3:
            # nothing to locate: control the opposite face's orientation to A (ISO 2768-2: parallelism
            # = the size tolerance or the flatness tolerance, whichever is larger)
            opp = self.bbox_face(axis_a, at_min=face_a.surface.normal[axis_a] > 0)  # the side opposite A
            if opp is not None:
                size = self.ir.bounding_box.size[axis_a]
                self.frame(G.PARALLELISM, max(linear_m(size), flatness_k(self.extent(opp))),
                           Target(face_id=opp.id), "A")
            self.refine_datum_features()
            return
        (axis_b, face_b), (axis_c, face_c) = sides[1], sides[2]
        self.datum("B", Target(face_id=face_b.id), "second bounding-box reference face (stops rotation)")
        self.datum("C", Target(face_id=face_c.id), "third bounding-box reference face (stops translation)")
        self.frame(G.PERPENDICULARITY, perpendicularity_k(self.extent(face_b)), Target(face_id=face_b.id), "A")
        self.frame(G.PERPENDICULARITY, perpendicularity_k(self.extent(face_c)), Target(face_id=face_c.id), "AB")
        bmin = self.ir.bounding_box.min

        def from_datums(h) -> float:
            pts = [self.features[m].axis.origin for m in getattr(h, "member_feature_ids", [])] or [h.axis.origin]
            return max(abs(p[i] - bmin[i]) for p in pts for i in (axis_b, axis_c))

        self.position_holes("ABC", from_datums)
        self.refine_datum_features()


def default_gdt(ir: GeometryIR, placed: list[DimensionCandidate], frames: list[Frame],
                roles: RoleResult | None = None, rules: RuleSet | None = None,
                toleranced: set[str] | None = None) -> DefaultGdt:
    """Datum reference frame + GD&T for the part, from GeometryIR (and the rule set's role treatments)."""
    b = _Builder(ir, placed, frames, roles, rules, toleranced)
    boss, k = b.main_boss()
    if boss is not None:
        b.rotational(boss, k)
    else:
        b.prismatic()
    if b.roles:
        b.special_roles()
        b.refine_datum_features()
    return b.out


__all__ = ["DEFAULT_GENERAL_TOLERANCE", "DefaultGdt", "default_gdt", "linear_m", "flatness_k",
           "perpendicularity_k", "position_zone", "tighter_than"]
