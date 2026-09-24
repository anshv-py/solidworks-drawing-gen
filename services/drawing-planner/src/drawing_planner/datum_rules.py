"""Datum-scheme rules: checks on the user's scheme, and a suggestion the user must confirm.

Checks (reported by QA, never auto-corrected):
  R3  datum features carry their own form control, tighter than what references them
  R7  process-specific datum features (no raw sheet edges; machined features on castings/weldments)
  R8  one datum, one job; no self-referencing frames
  R9  every datum on the drawing is referenced
  measurable tolerances (standard shop equipment)

Suggestion (rules 1, 2, 4, 5, 7): ranks GeometryIR features. Geometry cannot reveal function
(which surface mates, which is machined, what a fixture can reach), so the result is only
a proposal with reasons and cautions - nothing is put on the drawing until the user applies it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from drawing_schema.pmi import (
    FORM,
    GdtCharacteristic,
    ManufacturingAnnotations,
    ManufacturingProcess,
    Target,
    ToleranceKind,
)
from geometry_schema import FeatureType, GeometryIR, SurfaceType

MIN_SHOP_TOLERANCE = 0.01  # mm total zone: below this, verification needs special gauging / a CMM
PLANAR_FORM = {GdtCharacteristic.FLATNESS, GdtCharacteristic.STRAIGHTNESS}
SIZE_FORM = {GdtCharacteristic.CYLINDRICITY, GdtCharacteristic.CIRCULARITY, GdtCharacteristic.STRAIGHTNESS}
RAW_PROCESSES = {ManufacturingProcess.CASTING, ManufacturingProcess.FORGING, ManufacturingProcess.WELDMENT,
                 ManufacturingProcess.MOULDED}


@dataclass
class Finding:
    rule: str
    severity: str  # CRITICAL | MAJOR | MINOR
    message: str
    refs: list[str] = field(default_factory=list)


def _in_plane_extents(ir: GeometryIR, face) -> tuple[float, float]:
    ids = set(face.edge_ids)
    pts = [p for e in ir.edges if e.id in ids for p in (e.start, e.end)]
    if not pts:
        return (0.0, 0.0)
    n = face.surface.normal
    drop = max(range(3), key=lambda i: abs(n[i]))
    ext = sorted(max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3) if i != drop)
    return ext[0], ext[1]


def check_datum_scheme(ir: GeometryIR, m: ManufacturingAnnotations,
                       process: ManufacturingProcess = ManufacturingProcess.UNSPECIFIED) -> list[Finding]:
    out: list[Finding] = []
    faces = {f.id: f for f in ir.faces}
    features = {f.id: f for f in ir.features}
    by_letter = {d.letter: d for d in m.datums}

    # R8: one datum, one job
    seen: dict[str, str] = {}
    for d in m.datums:
        key = d.target.ref
        if key in seen:
            out.append(Finding("R8", "MAJOR", f"datums {seen[key]} and {d.letter} are the same feature - "
                                              "one datum feature, one job", [seen[key], d.letter]))
        seen[key] = d.letter
    for i, f in enumerate(m.frames, 1):
        for r in f.datums:
            d = by_letter.get(r.letter)
            if d is not None and d.target == f.target:
                out.append(Finding("R8", "MAJOR", f"frame {i} ({f.characteristic.value}) is on datum feature "
                                                  f"{r.letter} and references {r.letter} (self-referencing)",
                                   [r.letter]))

    # R9: every datum on the drawing is used
    referenced = {r.letter for f in m.frames for r in f.datums}
    for d in m.datums:
        if d.letter not in referenced:
            out.append(Finding("R9", "MAJOR", f"datum {d.letter} is not referenced by any feature control "
                                              "frame - reference it or delete it", [d.letter]))

    # R3: datum feature form refinement
    primaries = {f.datums[0].letter for f in m.frames if f.datums}
    for d in m.datums:
        if d.letter not in referenced:
            continue
        feat = features.get(d.target.feature_id) if d.target.feature_id else None
        allowed = SIZE_FORM if feat is not None else PLANAR_FORM
        own = [f for f in m.frames if f.target == d.target and not f.datums and f.characteristic in allowed]
        refs = [f.tolerance for f in m.frames if any(r.letter == d.letter for r in f.datums)]
        what = "cylindricity" if feat is not None else "flatness"
        if not own:
            sev = "MAJOR" if d.letter in primaries else "MINOR"
            out.append(Finding("R3", sev, f"datum feature {d.letter} has no {what} control - every tolerance "
                                          f"referencing {d.letter} inherits its form error", [d.letter]))
        elif refs and min(c.tolerance for c in own) >= min(refs):
            out.append(Finding("R3", "MAJOR", f"datum feature {d.letter} form tolerance "
                                              f"{min(c.tolerance for c in own):g} is not tighter than the "
                                              f"tolerances referencing it (smallest {min(refs):g})", [d.letter]))

    # R7: process-specific datum features
    if process == ManufacturingProcess.SHEET_METAL:
        thickness = min(ir.bounding_box.size)
        for d in m.datums:
            face = faces.get(d.target.face_id) if d.target.face_id else None
            if face is not None and face.surface_type == SurfaceType.PLANE:
                small, _ = _in_plane_extents(ir, face)
                if small <= 1.5 * thickness + 1e-6:
                    out.append(Finding("R7", "MAJOR", f"datum {d.letter} is a sheet edge face - use a sheet face "
                                                      "plus two holes, never a cut profile edge", [d.letter]))
    elif process in RAW_PROCESSES and m.datums:
        out.append(Finding("R5/R7", "MINOR", f"{process.value.lower()}: datum features must be machined "
                                             "(after welding for weldments) or defined by datum targets - "
                                             "confirm for " + ", ".join(sorted(by_letter))))

    # measurable with standard shop equipment
    for i, f in enumerate(m.frames, 1):
        if f.tolerance < MIN_SHOP_TOLERANCE:
            out.append(Finding("MEAS", "MAJOR", f"frame {i} ({f.characteristic.value}) zone {f.tolerance:g} mm "
                                                f"is below {MIN_SHOP_TOLERANCE} mm - not verifiable with standard "
                                                "shop equipment"))
    for t in m.tolerances:
        band = 2 * t.upper if t.kind == ToleranceKind.SYMMETRIC else t.upper - t.lower
        if band < MIN_SHOP_TOLERANCE:
            out.append(Finding("MEAS", "MAJOR", f"tolerance on {t.candidate_id} ({band:g} mm total) is below "
                                                f"{MIN_SHOP_TOLERANCE} mm - not verifiable with standard shop "
                                                "equipment", [t.candidate_id]))
    return out


# ---------------------------------------------------------------------------- suggestion

@dataclass
class DatumSuggestion:
    letter: str
    target: Target
    reasons: list[str]


def _unit_dot(a, b) -> float:
    return abs(sum(x * y for x, y in zip(a, b)))


def suggest_datums(ir: GeometryIR, process: ManufacturingProcess = ManufacturingProcess.UNSPECIFIED
                   ) -> tuple[list[DatumSuggestion], list[str]]:
    """-> (suggested A/B/C, cautions). Deterministic; the user must confirm."""
    cautions = [
        "Function is not visible in CAD geometry: confirm these are the surfaces that locate the part "
        "in its assembly (rule 1) - a machined pilot/boss that seats in a bore beats a larger flange face.",
        "Confirm every datum feature can be probed and clamped in each setup (rule 4).",
    ]
    if process in RAW_PROCESSES:
        cautions.append("Cast/forged/welded/moulded part: datum features must be machined (after welding) "
                        "or defined by datum targets (rules 5, 7).")
    if process == ManufacturingProcess.SHEET_METAL:
        cautions.append("Sheet metal: a sheet face plus two holes; never a raw or laser-cut edge (rule 7).")
    planes = [f for f in ir.faces if f.surface_type == SurfaceType.PLANE]
    if not planes:
        return [], cautions + ["No planar face: a primary datum must be chosen manually."]
    thickness = min(ir.bounding_box.size)

    def plane_key(f):
        n = f.surface.normal
        return tuple(round(x, 6) for x in n), round(sum(a * b for a, b in zip(n, f.centroid)), 4)

    groups: dict[tuple, list] = {}
    for f in planes:
        groups.setdefault(plane_key(f), []).append(f)
    axes = [f for f in ir.features if f.type in (FeatureType.HOLE, FeatureType.BOSS)]

    def primary_score(f):
        interrupted = len(groups[plane_key(f)]) > 1
        small, _ = _in_plane_extents(ir, f)
        edge_face = small <= 1.5 * thickness + 1e-6 and process == ManufacturingProcess.SHEET_METAL
        perp = sum(1 for a in axes if _unit_dot(a.axis.direction, f.surface.normal) > 1 - 1e-6)
        return (not edge_face, not interrupted, perp > 0, round(f.area, 3), f.id)

    # long turned part: the axis of its longest diameter is more stable than a small end face (rule 2)
    bb0 = ir.bounding_box
    ctr = [(bb0.min[i] + bb0.max[i]) / 2 for i in range(3)]
    bosses = [x for x in axes if x.type == FeatureType.BOSS]
    for bz in sorted(bosses, key=lambda x: (-x.height, -x.diameter, x.id)):
        d = bz.axis.direction
        k = max(range(3), key=lambda i: abs(d[i]))
        v = [ctr[i] - bz.axis.origin[i] for i in range(3)]
        t = sum(v[i] * d[i] for i in range(3))
        on_axis = math.dist(ctr, [bz.axis.origin[i] + t * d[i] for i in range(3)]) < 1e-3
        max_d = max(x.diameter for x in bosses)
        if on_axis and bb0.size[k] >= 1.5 * max_d:
            out = [DatumSuggestion("A", Target(feature_id=bz.id), [
                f"Ø{bz.diameter:.2f} × {bz.height:.2f} journal - the longest cylinder on the part axis gives "
                "the most stable, repeatable axis (rule 2)", "datum axis at RMB unless a gauge contacts it "
                "(then MMB, rule 6)"])]
            ends = [f for f in planes if _unit_dot(f.surface.normal, d) > 1 - 1e-6]
            if ends:
                e = max(ends, key=lambda f: (round(f.area, 3), f.id))
                out.append(DatumSuggestion("B", Target(face_id=e.id), [
                    f"shoulder/end face perpendicular to A, {e.area:.0f} mm² - fixes the axial position"]))
            cautions.append("Axisymmetric part: no clocking datum is needed unless an off-axis feature "
                            "must be oriented.")
            return out, cautions

    a = max(planes, key=primary_score)
    reasons_a = [f"planar face, {a.area:.0f} mm² (area used only as a tie-breaker)"]
    if len(groups[plane_key(a)]) == 1:
        reasons_a.append("continuous (not split into separate coplanar pads)")
    if any(_unit_dot(x.axis.direction, a.surface.normal) > 1 - 1e-6 for x in axes):
        reasons_a.append("perpendicular to the part's hole/boss axes - orients them")
    out = [DatumSuggestion("A", Target(face_id=a.id), reasons_a)]

    n = a.surface.normal
    par = [x for x in axes if _unit_dot(x.axis.direction, n) > 1 - 1e-6]
    bb = ir.bounding_box
    centre = [(bb.min[i] + bb.max[i]) / 2 for i in range(3)]

    def line_dist(p, o, d) -> float:
        """distance of point p from the line through o along unit d"""
        v = [p[i] - o[i] for i in range(3)]
        t = sum(v[i] * d[i] for i in range(3))
        return math.dist(p, [o[i] + t * d[i] for i in range(3)])

    def off_axis(x) -> float:
        return line_dist(centre, x.axis.origin, x.axis.direction)

    b = None
    if par:
        if process == ManufacturingProcess.SHEET_METAL:
            b = max(par, key=lambda x: (x.type == FeatureType.HOLE, x.diameter, x.id))
            why = "largest hole perpendicular to A (face + two holes)"
        else:
            central = [x for x in par if off_axis(x) < 1e-3]
            pool = central or par
            outer = max((x.diameter for x in pool if x.type == FeatureType.BOSS), default=None)

            def rank(x):
                # rule 1: a pilot boss (not the outer body) that seats in a bore, then a bore, then the
                # outer diameter; size only breaks ties
                pilot = x.type == FeatureType.BOSS and outer is not None and x.diameter < outer - 1e-9
                return (2 if pilot else 1 if x.type == FeatureType.HOLE else 0, x.diameter, x.id)

            b = max(pool, key=rank)
            why = ("feature of size on the part's main axis" if central else "largest feature of size "
                   "perpendicular to A")
        out.append(DatumSuggestion("B", Target(feature_id=b.id), [
            f"Ø{b.diameter:.2f} {b.type.value.lower()} - {why}", "datum axis at RMB unless a gauge pin "
            "contacts it in service (then MMB, rule 6)"]))
        rest = [x for x in par if x.type == FeatureType.HOLE
                and line_dist(x.axis.origin, b.axis.origin, b.axis.direction) > 1e-3]
        if rest:
            c = max(rest, key=lambda x: (math.dist(x.axis.origin, b.axis.origin), x.id))
            out.append(DatumSuggestion("C", Target(feature_id=c.id), [
                f"Ø{c.diameter:.2f} hole away from B - stops rotation about B (clocking)"]))
    if len(out) < 3:
        perp_faces = [f for f in planes if _unit_dot(f.surface.normal, n) < 1e-6]
        used = {s.target.ref for s in out}
        perp_faces = [f for f in perp_faces if f.id not in used]
        for letter in ("B", "C")[len(out) - 1:]:
            if not perp_faces:
                break
            cand = max(perp_faces, key=lambda f: (round(f.area, 3), f.id))
            perp_faces = [f for f in perp_faces
                          if _unit_dot(f.surface.normal, cand.surface.normal) < 1e-6 and f.id != cand.id]
            out.append(DatumSuggestion(letter, Target(face_id=cand.id), [
                f"planar face perpendicular to A{' and B' if letter == 'C' else ''}, {cand.area:.0f} mm²"]))
    if process not in (ManufacturingProcess.UNSPECIFIED, ManufacturingProcess.CNC_MACHINED,
                       ManufacturingProcess.ADDITIVE, ManufacturingProcess.SHEET_METAL):
        for s in out:
            s.reasons.append("must be a machined surface/feature (or use datum targets)")
    return out, cautions


__all__ = ["Finding", "check_datum_scheme", "DatumSuggestion", "suggest_datums", "MIN_SHOP_TOLERANCE", "FORM"]
