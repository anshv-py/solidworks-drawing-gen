"""Check user-supplied manufacturing annotations against the part's actual geometry.

Nothing is corrected or guessed: invalid entries are reported and the drawing is not generated.
"""

from __future__ import annotations

import re

from drawing_schema.candidates import DimensionCandidate
from drawing_schema.pmi import (
    ManufacturingAnnotations,
    MaterialCondition,
    Target,
)
from geometry_schema import FeatureType, GeometryIR, SurfaceType

SIZE_FEATURES = {FeatureType.HOLE, FeatureType.BOSS, FeatureType.SLOT, FeatureType.PATTERN}
AXIS_FEATURES = {FeatureType.HOLE, FeatureType.BOSS, FeatureType.PATTERN}
_METRIC = re.compile(r"^\s*M\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


def _describe(t: Target) -> str:
    return t.feature_id or t.face_id or "?"


def validate_pmi(ir: GeometryIR, m: ManufacturingAnnotations,
                 placed_candidates: list[DimensionCandidate] | None = None) -> list[str]:
    """Return human-readable errors (empty list = valid)."""
    errors: list[str] = []
    features = {f.id: f for f in ir.features}
    faces = {f.id: f for f in ir.faces}

    def check_target(t: Target, what: str, *, planar_face_only: bool = False) -> None:
        if t.feature_id is not None and t.feature_id not in features:
            errors.append(f"{what}: feature {t.feature_id} does not exist on this part")
        if t.face_id is not None:
            face = faces.get(t.face_id)
            if face is None:
                errors.append(f"{what}: face {t.face_id} does not exist on this part")
            elif planar_face_only and face.surface_type != SurfaceType.PLANE:
                errors.append(f"{what}: face {t.face_id} is not planar - select the hole/boss feature instead")

    for d in m.datums:
        check_target(d.target, f"datum {d.letter}", planar_face_only=True)
    for i, fr in enumerate(m.frames, 1):
        what = f"GD&T frame {i} ({fr.characteristic.value})"
        check_target(fr.target, what)
        feat = features.get(fr.target.feature_id) if fr.target.feature_id else None
        if fr.material_condition and (feat is None or feat.type not in SIZE_FEATURES):
            errors.append(f"{what}: {fr.material_condition.value} applies only to a feature of size "
                          "(hole, boss, slot or pattern)")
        if fr.diameter_zone and (feat is None or feat.type not in AXIS_FEATURES):
            errors.append(f"{what}: a Ø zone needs an axis feature (hole, boss or hole pattern)")
        for ref in fr.datums:
            datum = next((d for d in m.datums if d.letter == ref.letter), None)
            if ref.material_condition == MaterialCondition.MMC and datum is not None:
                df = features.get(datum.target.feature_id) if datum.target.feature_id else None
                if df is None or df.type not in SIZE_FEATURES:
                    errors.append(f"{what}: datum {ref.letter} is a face, so it cannot take a material condition")
        if fr.characteristic.value == "FLATNESS":
            face = faces.get(fr.target.face_id) if fr.target.face_id else None
            if face is None or face.surface_type != SurfaceType.PLANE:
                errors.append(f"{what}: flatness applies to a planar face")

    placed = {c.id: c for c in (placed_candidates or [])}
    if placed_candidates is not None:
        for t in m.tolerances:
            if t.candidate_id not in placed:
                errors.append(f"tolerance: dimension {t.candidate_id} is not on the drawing")
        for cid in m.inspection_dimensions:
            if cid not in placed:
                errors.append(f"inspection mark: dimension {cid} is not on the drawing")
        for cid in m.basic_dimensions:
            if cid not in placed:
                errors.append(f"basic (TED) mark: dimension {cid} is not on the drawing")

    for th in m.threads:
        h = features.get(th.feature_id)
        if h is None or h.type != FeatureType.HOLE:
            errors.append(f"thread {th.designation}: {th.feature_id} is not a hole")
            continue
        if not h.through and th.depth is None:
            errors.append(f"thread {th.designation}: the hole is blind - give the thread depth")
        if th.depth is not None and th.depth > h.depth + 1e-6:
            errors.append(f"thread {th.designation}: thread depth {th.depth} exceeds the hole depth {h.depth:.2f}")
        mm = _METRIC.match(th.designation)
        if mm and h.diameter > float(mm.group(1)) + 1e-6:
            errors.append(f"thread {th.designation}: the modelled hole Ø{h.diameter:.2f} is larger than the "
                          f"thread's nominal diameter")

    for s in m.surface_finish_marks:
        check_target(s.target, f"surface finish Ra {s.ra_um}", planar_face_only=True)
    for n in m.feature_notes:
        check_target(n.target, f"note '{n.text}'")
    return errors
