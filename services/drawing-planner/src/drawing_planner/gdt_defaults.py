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
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from drawing_schema.candidates import CandidateKind, CandidateRole, DimensionCandidate
from drawing_schema.frames import Frame, dot
from drawing_schema.pmi import (
    Datum,
    DatumReference,
    FeatureControlFrame,
    GdtCharacteristic as G,
    Target,
)
from geometry_schema import FeatureType, GeometryIR, SurfaceType

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
    rationale: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.datums or self.frames)


class _Builder:
    def __init__(self, ir: GeometryIR, placed: list[DimensionCandidate], frames: list[Frame]) -> None:
        self.ir = ir
        self.placed = placed
        self.frames = frames
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

    # ------------------------------------------------------------------ emitters
    def datum(self, letter: str, target: Target, why: str) -> None:
        self.out.datums.append(Datum(letter=letter, target=target))
        self.out.rationale.append(f"datum {letter} = {target.ref}: {why}")

    def frame(self, ch: G, tol: float, target: Target, refs: str = "", diameter: bool = False) -> None:
        self.out.frames.append(FeatureControlFrame(
            characteristic=ch, tolerance=round(tol, 3), diameter_zone=diameter, target=target,
            datums=[DatumReference(letter=r) for r in refs]))

    def position_holes(self, refs: str, locating_length) -> None:
        """One position frame per hole callout (a callout may cover several unpatterned holes)."""
        ted_ids: set[str] = set()
        for c in sorted((c for c in self.placed if c.kind == CandidateKind.HOLE_CALLOUT), key=lambda c: c.id):
            holes = [h for h in self.hole_targets if self._ids(h.id) & set(c.feature_ids)]
            if not holes:
                continue
            target = next((h for h in holes if h.type == FeatureType.PATTERN), min(holes, key=lambda h: h.id))
            zone = min(position_zone(locating_length(h)) for h in holes)
            self.frame(G.POSITION, zone, Target(feature_id=target.id), refs, diameter=True)
            for h in holes:
                ted_ids |= self._ids(h.id)
        for c in self.placed:
            if ted_ids & set(c.feature_ids) and (c.role in (CandidateRole.LOCATION, CandidateRole.PITCH)
                                                 or c.kind == CandidateKind.PCD):
                self.out.basic_dimensions.append(c.id)

    def refine_datum_features(self) -> None:
        """Rule 3: each datum feature's own control tighter than everything referencing it."""
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
        bb = self.ir.bounding_box
        ctr = [(bb.min[i] + bb.max[i]) / 2 for i in range(3)]
        for b in sorted((f for f in self.ir.features if f.type == FeatureType.BOSS),
                        key=lambda b: (-b.diameter, b.id)):
            d = b.axis.direction
            k = max(range(3), key=lambda i: abs(d[i]))
            if abs(abs(d[k]) - 1) > _EPS:
                continue
            off = [ctr[i] - b.axis.origin[i] for i in range(3) if i != k]
            across = [bb.size[i] for i in range(3) if i != k]
            if math.hypot(*off) < 1e-3 and all(abs(s - b.diameter) < 1e-3 * max(1.0, b.diameter) for s in across):
                return b, k
        return None, None

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

        if bb.size[k] >= 1.5 * boss.diameter:  # shaft: the longest journal's axis is the primary datum
            journals = [b for b in coaxial if self.has_diameter(b.id)]
            if not journals:
                return
            a = max(journals, key=lambda b: (b.height, b.diameter, b.id))
            self.datum("A", Target(feature_id=a.id), f"Ø{a.diameter:g} journal - longest diameter on the part axis")
            self.frame(G.STRAIGHTNESS, flatness_k(a.height), Target(feature_id=a.id), diameter=True)
            for b in journals:
                if b.id != a.id:
                    self.frame(G.CIRCULAR_RUNOUT, RUNOUT_K, Target(feature_id=b.id), "A")
            if shoulder is not None:
                self.frame(G.CIRCULAR_RUNOUT, RUNOUT_K, Target(face_id=shoulder.id), "A")
            self.refine_datum_features()
            return

        # disc / flange: seating face first, the main diameter's axis centres the part
        if shoulder is None:
            return
        self.datum("A", Target(face_id=shoulder.id), "largest face perpendicular to the part axis (seating face)")
        self.frame(G.FLATNESS, flatness_k(self.extent(shoulder)), Target(face_id=shoulder.id))
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

    def prismatic(self) -> None:
        sides = [(i, f) for i in range(3) if (f := self.bbox_face(i, at_min=True)) is not None]
        if not sides:
            return
        sides.sort(key=lambda s: (-round(s[1].area, 3), s[1].id))
        axis_a, face_a = sides[0]
        located = [h for h in self.hole_targets if self.has_callout(h.id)]
        self.datum("A", Target(face_id=face_a.id), "largest bounding-box reference face (seating face)")
        self.frame(G.FLATNESS, flatness_k(self.extent(face_a)), Target(face_id=face_a.id))
        if not located or len(sides) < 3:
            # nothing to locate: control the opposite face's orientation to A (ISO 2768-2: parallelism
            # = the size tolerance or the flatness tolerance, whichever is larger)
            opp = self.bbox_face(axis_a, at_min=False)
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


def default_gdt(ir: GeometryIR, placed: list[DimensionCandidate], frames: list[Frame]) -> DefaultGdt:
    """Datum reference frame + GD&T for the part, from GeometryIR only (deterministic)."""
    b = _Builder(ir, placed, frames)
    boss, k = b.main_boss()
    if boss is not None:
        b.rotational(boss, k)
    else:
        b.prismatic()
    return b.out


__all__ = ["DEFAULT_GENERAL_TOLERANCE", "DefaultGdt", "default_gdt", "linear_m", "flatness_k",
           "perpendicularity_k", "position_zone", "tighter_than"]
