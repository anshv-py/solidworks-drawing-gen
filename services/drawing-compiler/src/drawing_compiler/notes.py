"""Default drawing notes, assembled deterministically.

Order (fixed): 1 standard/units/projection/do-not-scale · 2 general linear tolerance ·
3 general geometric tolerance · 4 datum reference frame · 5 envelope (ASME) / independency (ISO) ·
6 datum feature form refinement · 7 surface finish · 8 deburr / edge break · 9 material ·
10 heat treatment / coating / masking · 11 thread class · 12 process sequence · 13 drawing governs
model · 14 inspection · 15 marking · then user notes · "WHAT THE SUPPLIER MUST NOT ASSUME" ·
one summary line.

Values come only from the user's settings and from GeometryIR (datum feature descriptions, the
model file name). Anything not supplied is printed as a [PLACEHOLDER]; nothing is guessed.
"""

from __future__ import annotations

import re

from drawing_schema import DrawingPlan, DrawingStandard
from drawing_schema.pmi import FORM, GdtCharacteristic, ManufacturingProcess, Target
from geometry_schema import FeatureType, GeometryIR, SurfaceType

PLACEHOLDER = re.compile(r"\[[A-Z0-9][A-Z0-9 /.,&()'-]*\]")
_AXES = "XYZ"
_PROCESS = {
    ManufacturingProcess.CNC_MACHINED: "CNC MACHINED", ManufacturingProcess.SHEET_METAL: "SHEET METAL",
    ManufacturingProcess.CASTING: "CASTING", ManufacturingProcess.FORGING: "FORGING",
    ManufacturingProcess.WELDMENT: "WELDMENT", ManufacturingProcess.MOULDED: "MOULDED",
    ManufacturingProcess.ADDITIVE: "ADDITIVE",
}
SUPPLIER_MUST_NOT_ASSUME = [
    "DATUMS OTHER THAN THOSE IN NOTE 4 - DO NOT RE-DATUM OR RE-FIXTURE TO OTHER FEATURES WITHOUT WRITTEN APPROVAL.",
    "THAT A DIMENSION IS REFERENCE, UNTOLERANCED OR FREE - NOTES 2 AND 3 APPLY UNLESS OTHERWISE SPECIFIED.",
    "THAT MATERIAL, HEAT TREATMENT, COATING OR PROCESS SUBSTITUTES ARE ACCEPTABLE.",
    "THAT THE 3D MODEL OVERRIDES THIS DRAWING, OR THAT ANY VALUE MAY BE SCALED FROM IT.",
]


def _v(value: str | None, placeholder: str) -> str:
    v = (value or "").strip()
    return v if v else f"[{placeholder}]"  # user values print exactly as entered


def _eng(plan: DrawingPlan, name: str) -> str | None:
    f = getattr(plan.engineering_information, name)
    return f.value if f.status == "SPECIFIED" else None


def _num(v: float) -> str:
    return f"{v:.2f}"


def describe_target(ir: GeometryIR, t: Target) -> str:
    """The real feature behind a datum, in drawing language (from GeometryIR only)."""
    if t.face_id:
        face = next((f for f in ir.faces if f.id == t.face_id), None)
        if face is None:
            return t.face_id
        if face.surface_type == SurfaceType.PLANE:
            n = face.surface.normal
            k = max(range(3), key=lambda i: abs(n[i]))
            if abs(abs(n[k]) - 1) < 1e-6:
                return (f"PLANAR FACE {'+' if n[k] > 0 else '-'}{_AXES[k]} "
                        f"({_AXES[k]} = {_num(face.centroid[k])})")
            return "INCLINED PLANAR FACE"
        return f"{face.surface_type.value} FACE"
    feat = next((f for f in ir.features if f.id == t.feature_id), None)
    if feat is None:
        return t.feature_id or "?"
    if feat.type == FeatureType.HOLE:
        return f"Ø{_num(feat.diameter)} HOLE AXIS"
    if feat.type == FeatureType.BOSS:
        return f"Ø{_num(feat.diameter)} BOSS AXIS"
    if feat.type == FeatureType.PATTERN:
        n = len(feat.member_feature_ids)
        return f"{n}X HOLE PATTERN (AXES)"
    if feat.type == FeatureType.SLOT:
        return f"SLOT {_num(feat.width)} WIDE (CENTER PLANE)"
    return feat.type.value


def _form_note(plan: DrawingPlan) -> str:
    m = plan.manufacturing
    if not m.datums:
        return ("DATUM FEATURE FORM: [FORM TOLERANCE ON EACH DATUM FEATURE], TIGHTER THAN EVERY "
                "TOLERANCE REFERENCING THAT DATUM.")
    parts = []
    for d in sorted(m.datums, key=lambda d: d.letter):
        refs = [f.tolerance for f in m.frames if any(r.letter == d.letter for r in f.datums)]
        own = [f for f in m.frames if f.target == d.target and not f.datums and f.characteristic in FORM]
        if own:
            c = own[0]
            parts.append(f"{d.letter}: {c.characteristic.value.replace('_', ' ')} {_num(c.tolerance)}")
        else:
            limit = f" < {_num(min(refs))}" if refs else ""
            parts.append(f"{d.letter}: [FORM TOLERANCE{limit}]")
    return ("DATUM FEATURE FORM (REFINES ALL TOLERANCES REFERENCING THE DATUM): " + "; ".join(parts) + ".")


def build_notes(plan: DrawingPlan, ir: GeometryIR) -> tuple[list[str], list[str], str]:
    """-> (numbered notes, supplier bullets, summary line)."""
    g = plan.general_notes
    m = plan.manufacturing
    asme = plan.drawing_standard == DrawingStandard.ASME
    projection = plan.projection_method.value.replace("_", " ")
    standard = "ASME Y14.5-2018" if asme else "ISO GPS (ISO 8015, ISO 1101, ISO 5459)"
    linear = _eng(plan, "linear_tolerance") or _eng(plan, "general_tolerance")
    angular = _eng(plan, "angular_tolerance") or _eng(plan, "general_tolerance")
    geo = g.general_geometric_tolerance
    datums = sorted(m.datums, key=lambda d: d.letter)
    frame = ("; ".join(f"{d.letter} = {describe_target(ir, d.target)}" for d in datums) + "."
             if datums else "[DATUM A: FEATURE]; [DATUM B: FEATURE]; [DATUM C: FEATURE].")
    finish = _eng(plan, "surface_finish")
    pointer = ("SEE SURFACE TEXTURE SYMBOLS FOR SPECIFIC SURFACES." if m.surface_finish_marks
               else "NO SURFACE-SPECIFIC CALLOUTS.")
    if m.deburr_break_sharp_edges or g.edge_break:
        edges = f"REMOVE ALL BURRS. BREAK SHARP EDGES {_v(g.edge_break, 'EDGE BREAK VALUE')}."
    else:
        edges = "[BURR / SHARP-EDGE REQUIREMENT AND EDGE BREAK VALUE]."
    process = _PROCESS.get(g.process) or _eng(plan, "manufacturing_process") or "[PROCESS]"
    model = ir.source.filename
    model_rev = g.model_revision or plan.title_block.revision
    inspection = _eng(plan, "inspection_requirements")
    insp_extra = " DIMENSIONS IN OVAL FRAMES ARE INSPECTION DIMENSIONS." if m.inspection_dimensions else ""
    notes = [
        f"DIMENSIONING AND TOLERANCING PER {standard}. ALL DIMENSIONS IN MM. {projection} PROJECTION. "
        "DO NOT SCALE DRAWING.",
        f"GENERAL TOLERANCES UNLESS OTHERWISE SPECIFIED - LINEAR: {_v(linear, 'GENERAL LINEAR TOLERANCE')}; "
        f"ANGULAR: {_v(angular, 'GENERAL ANGULAR TOLERANCE')}.",
        f"GENERAL GEOMETRIC TOLERANCE UNLESS OTHERWISE SPECIFIED: {_v(geo, 'GENERAL GEOMETRIC TOLERANCE')}.",
        f"DATUM REFERENCE FRAME: {frame}",
        ("RULE #1 (ENVELOPE PRINCIPLE) APPLIES TO ALL REGULAR FEATURES OF SIZE UNLESS NOTED INDEPENDENT. "
         "DATUM FEATURES OF SIZE APPLY AT RMB UNLESS MMB/LMB IS SHOWN." if asme else
         "INDEPENDENCY PRINCIPLE PER ISO 8015 APPLIES; ENVELOPE REQUIREMENT ONLY WHERE (E) IS SHOWN."),
        _form_note(plan),
        f"SURFACE FINISH UNLESS OTHERWISE SPECIFIED: {_v(finish, 'DEFAULT SURFACE FINISH')}. {pointer}",
        edges,
        f"MATERIAL: {_v(_eng(plan, 'material'), 'MATERIAL')}. NO SUBSTITUTION WITHOUT WRITTEN APPROVAL.",
        f"HEAT TREATMENT: {_v(_eng(plan, 'heat_treatment'), 'HEAT TREATMENT OR NONE')}. "
        f"COATING: {_v(_eng(plan, 'coating'), 'COATING OR NONE')}. "
        f"MASK: {_v(g.masked_surfaces, 'SURFACES TO BE MASKED OR NONE')}.",
        f"THREADS UNLESS OTHERWISE SPECIFIED: {_v(g.thread_class, 'THREAD CLASS')}.",
        f"PROCESS: {process}. SEQUENCE: {_v(g.process_sequence, 'MACHINING VS HT/COATING SEQUENCE')}.",
        f"THIS DRAWING GOVERNS 3D MODEL {model} REV {_v(model_rev, 'MODEL REV')}; "
        "REPORT ANY CONFLICT BEFORE MANUFACTURE.",
        f"INSPECTION / DOCUMENTATION: {_v(inspection, 'INSPECTION LEVEL, FAI AND CERTIFICATES REQUIRED')}."
        + insp_extra,
        f"MARKING / TRACEABILITY: {_v(g.marking, 'CONTENT, METHOD AND LOCATION')}.",
    ]
    notes += [n.strip() for n in m.notes if n.strip()]
    bullets = list(SUPPLIER_MUST_NOT_ASSUME) if g.supplier_bullets else []
    summary = (f"CONTROLLING STANDARD: {standard} | GENERAL LINEAR TOL: {_v(linear, 'GENERAL LINEAR TOLERANCE')} | "
               f"GENERAL GEOMETRIC TOL: {_v(geo, 'GENERAL GEOMETRIC TOLERANCE')}")
    return notes, bullets, summary


def placeholders(lines: list[str]) -> list[str]:
    return [p for line in lines for p in PLACEHOLDER.findall(line)]


# characteristics used as the datum feature's own form control (rule 3)
FORM_CONTROLS = FORM | {GdtCharacteristic.PROFILE_OF_A_SURFACE}
