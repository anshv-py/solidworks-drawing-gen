"""Deterministic drawing QA.

Several checks compare two *independent* computations: the compiler's analytic projection of
GeometryIR, and OCCT's hidden-line-removal output of the actual B-Rep. Disagreement means the
drawing does not show what the plan claims (wrong orientation, wrong extent, leader pointing
at nothing), so those checks are critical.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from drawing_schema import DRAWING_SCALES, ISO_5455_SCALES, DrawingPlan, ProjectionMethod, ViewOrientation
from drawing_schema.candidates import CandidateKind, CandidateRole, DimensionCandidate
from drawing_schema.compiled import AnnotationKind, CompiledDrawing, DimensionOpKind, Rect
from drawing_schema.qa import QaIssue, QaReport, QaSeverity
from geometry_schema import FeatureType, GeometryIR

Polyline = list[tuple[float, float]]

REDUCE_SCALE = "REDUCE_SCALE"
INCREASE_TIER_GAP = "INCREASE_TIER_GAP"
CLEARANCE = 1.0
MIN_TEXT = 2.5


@dataclass
class Rendered:
    """What the executor actually drew, in sheet mm."""

    lines: dict[str, dict[str, list[Polyline]]]  # view id -> {"visible": [...], "hidden": [...]}
    snapped: dict[str, tuple] = field(default_factory=dict)  # dim id -> (p1, p2)
    hatches: dict[str, list] = field(default_factory=dict)  # section view id -> [[loop, ...] per cut face]


def _bbox(polys: list[Polyline]) -> Rect | None:
    pts = [p for pl in polys for p in pl]
    if not pts:
        return None
    return Rect(x0=min(p[0] for p in pts), y0=min(p[1] for p in pts),
                x1=max(p[0] for p in pts), y1=max(p[1] for p in pts))


def _dist_to_polys(p, polys: list[Polyline]) -> float:
    best = math.inf
    for pl in polys:
        for a, b in zip(pl, pl[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
            best = min(best, math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy))
    return best


def _circle_polys(center, r, n=128) -> Polyline:
    return [(center[0] + r * math.cos(2 * math.pi * k / n), center[1] + r * math.sin(2 * math.pi * k / n))
            for k in range(n + 1)]


class _Report:
    def __init__(self) -> None:
        self.issues: list[QaIssue] = []
        self.checks: list[str] = []

    def check(self, cid: str) -> None:
        self.checks.append(cid)

    def add(self, cid, sev, msg, refs=(), bbox=None, repair=None) -> None:
        self.issues.append(QaIssue(check_id=cid, severity=sev, message=msg, entity_refs=list(refs),
                                   bbox=bbox, repair=repair))


def validate(plan: DrawingPlan, candidates: list[DimensionCandidate], ir: GeometryIR,
             cd: CompiledDrawing, rendered: Rendered, iteration: int = 1) -> QaReport:
    R = _Report()
    cands = {c.id: c for c in candidates}
    views = {v.id: v for v in cd.views}
    geo_bbox = {vid: _bbox(ls["visible"] + ls["hidden"]) for vid, ls in rendered.lines.items()}

    # ---------------------------------------------------------------- sheet
    R.check("QA-SHEET-001")
    for vid, bb in geo_bbox.items():
        if bb is None:
            R.add("QA-VIEW-006", QaSeverity.CRITICAL, f"view {vid} produced no geometry", [vid])
        elif not bb.inside(cd.frame):
            R.add("QA-SHEET-001", QaSeverity.CRITICAL, f"view {vid} extends outside the drawing frame",
                  [vid], bb, REDUCE_SCALE)
    R.check("QA-SHEET-002")
    for d in cd.dimensions:
        pts = [p for p in (d.p1, d.p2) if p] + list(d.leader)
        box = d.text_bbox if d.extra_bbox is None else d.text_bbox.union(d.extra_bbox)
        for p in pts:
            box = box.union(Rect(x0=p[0], y0=p[1], x1=p[0], y1=p[1]))
        if not box.inside(cd.frame):
            R.add("QA-SHEET-002", QaSeverity.CRITICAL, f"dimension {d.id} ({d.text}) extends outside the frame",
                  [d.id], box, REDUCE_SCALE)
    for p in cd.pmi:
        if not p.bbox.inside(cd.frame):
            R.add("QA-SHEET-002", QaSeverity.CRITICAL, f"annotation {p.id} extends outside the frame",
                  [p.id], p.bbox, REDUCE_SCALE)
    R.check("QA-SHEET-003")
    blocks = [("title block", cd.title_block)]
    if cd.notes_rect is not None:
        blocks.append(("sheet notes", cd.notes_rect))
    if cd.revision_rect is not None:
        blocks.append(("revision table", cd.revision_rect))
    if cd.stamp is not None:
        blocks.append(("release stamp", cd.stamp.rect))
    drawn =[(f"view {vid}", vid, bb) for vid, bb in geo_bbox.items() if bb is not None]
    drawn += [(f"dimension {d.id}", d.id, d.text_bbox) for d in cd.dimensions]
    drawn += [(f"annotations of {d.id}", d.id, d.extra_bbox) for d in cd.dimensions if d.extra_bbox]
    drawn += [(f"annotation {p.id}", p.id, p.bbox) for p in cd.pmi]
    for what, ref, bb in drawn:
        for name, blk in blocks:
            if bb.intersects(blk):
                R.add("QA-SHEET-003", QaSeverity.CRITICAL, f"{what} collides with the {name}", [ref], bb,
                      REDUCE_SCALE)

    # ---------------------------------------------------------------- views
    R.check("QA-VIEW-001")
    ids = sorted(k for k, b in geo_bbox.items() if b is not None)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if geo_bbox[a].intersects(geo_bbox[b], clearance=CLEARANCE):
                R.add("QA-VIEW-001", QaSeverity.CRITICAL, f"views {a} and {b} overlap", [a, b],
                      geo_bbox[a].union(geo_bbox[b]), REDUCE_SCALE)
    R.check("QA-VIEW-002")
    for v in cd.views:
        bb = geo_bbox.get(v.id)
        if v.pictorial or bb is None or v.detail_of:  # (a detail shows a region only)
            continue
        # HLR extents (OCCT) must equal the GeometryIR bounding box projected by the compiler
        tol = 0.05 * v.scale_factor + 0.01
        if v.cut_point is not None:
            # a section shows the half behind the plane: never larger than the part, possibly smaller
            if bb.w > v.outline.w + tol or bb.h > v.outline.h + tol:
                R.add("QA-VIEW-002", QaSeverity.CRITICAL, f"section {v.id} is drawn larger than the part", [v.id], bb)
            continue
        if abs(bb.w - v.outline.w) > tol or abs(bb.h - v.outline.h) > tol:
            R.add("QA-VIEW-002", QaSeverity.CRITICAL,
                  f"view {v.id}: drawn extent {bb.w / v.scale_factor:.3f} x {bb.h / v.scale_factor:.3f} mm "
                  f"differs from GeometryIR {v.outline.w / v.scale_factor:.3f} x {v.outline.h / v.scale_factor:.3f} mm",
                  [v.id], bb)
    R.check("QA-SEC-001")
    # every section is hatched and its cutting plane (same letter) is shown in another view
    for v in cd.views:
        if v.cut_point is None:
            continue
        letter = (v.label or "-").split("-")[0]
        if not rendered.hatches.get(v.id):
            R.add("QA-SEC-001", QaSeverity.CRITICAL, f"section {v.label} has no hatched cut face", [v.id])
        if not any(a.kind == AnnotationKind.SECTION_LINE and a.label == letter and a.view_id != v.id
                   for a in cd.annotations):
            R.add("QA-SEC-001", QaSeverity.CRITICAL, f"cutting plane {letter}-{letter} is not shown in any view",
                  [v.id])
    R.check("QA-DET-001")
    # every detail shows geometry and its region is circled with the same letter in the view it enlarges
    for v in cd.views:
        if not v.detail_of:
            continue
        letter = (v.label or "").split(" ")[0]
        circles = [a for a in cd.annotations if a.kind == AnnotationKind.DETAIL_CIRCLE and a.label == letter]
        if not any(a.view_id == v.detail_of for a in circles):
            R.add("QA-DET-001", QaSeverity.CRITICAL, f"detail {letter} is not circled in {v.detail_of}", [v.id])
        drawn = rendered.lines.get(v.id, {})
        if not (drawn.get("visible") or drawn.get("hidden")):
            R.add("QA-DET-001", QaSeverity.CRITICAL, f"detail {letter} shows no geometry", [v.id])
    R.check("QA-VIEW-003")
    front = next((v for v in cd.views if v.orientation == ViewOrientation.FRONT and not v.detail_of), None)
    if front is not None:
        first = cd.projection_method == ProjectionMethod.FIRST_ANGLE
        expect = {  # orientation -> (axis, sign) of offset from FRONT
            ViewOrientation.TOP: ("y", -1 if first else 1), ViewOrientation.BOTTOM: ("y", 1 if first else -1),
            ViewOrientation.RIGHT: ("x", -1 if first else 1), ViewOrientation.LEFT: ("x", 1 if first else -1),
        }
        fx, fy = front.sheet_center
        for v in cd.views:
            if v.orientation not in expect or v.detail_of:  # details float freely
                continue
            axis, sign = expect[v.orientation]
            dx, dy = v.sheet_center[0] - fx, v.sheet_center[1] - fy
            along, across = (dy, dx) if axis == "y" else (dx, dy)
            if along * sign <= 0 or abs(across) > 1e-6:
                R.add("QA-VIEW-003", QaSeverity.CRITICAL,
                      f"{v.id} is not placed per {cd.projection_method.value} projection relative to FRONT", [v.id])
    R.check("QA-VIEW-004")
    for v in cd.views:
        if v.scale not in DRAWING_SCALES:
            R.add("QA-VIEW-004", QaSeverity.MAJOR, f"{v.id} scale {v.scale} is not a supported drawing scale", [v.id])
        elif v.scale not in ISO_5455_SCALES:
            R.add("QA-VIEW-004", QaSeverity.MINOR, f"{v.id} scale {v.scale} is an intermediate (non-ISO 5455) scale",
                  [v.id])
    R.check("QA-VIEW-005")
    usable = Rect(x0=cd.frame.x0, y0=cd.title_block.y1, x1=cd.frame.x1, y1=cd.frame.y1)
    filled = sum(b.w * b.h for b in geo_bbox.values() if b is not None)
    if filled / (usable.w * usable.h) < 0.08:
        R.add("QA-VIEW-005", QaSeverity.MINOR, "views occupy less than 8 % of the drawing area")

    # ---------------------------------------------------------------- dimensions
    placed = [d.id for d in cd.dimensions]
    R.check("QA-DIM-001")
    for d in cd.dimensions:
        c = cands.get(d.id)
        v = views[d.view_id]
        if c is None:
            R.add("QA-REF-001", QaSeverity.CRITICAL, f"dimension {d.id} does not reference a known candidate", [d.id])
            continue
        if abs(d.value - c.value) > 1e-9 or d.text != c.text:
            R.add("QA-DIM-001", QaSeverity.CRITICAL, f"{d.id}: printed value differs from GeometryIR", [d.id])
        if d.kind == DimensionOpKind.LINEAR:
            measured = abs(d.p2[0] - d.p1[0]) if d.horizontal else abs(d.p2[1] - d.p1[1])
            if abs(measured / v.scale_factor - c.value) > 1e-3:
                R.add("QA-DIM-001", QaSeverity.CRITICAL,
                      f"{d.id}: sheet geometry measures {measured / v.scale_factor:.4f} mm but label says {c.text}",
                      [d.id])
            if c.role == CandidateRole.OVERALL:
                bb = geo_bbox.get(d.view_id)
                drawn = (bb.w if d.horizontal else bb.h) / v.scale_factor if bb else None
                if drawn is None or abs(drawn - c.value) > 0.05:
                    R.add("QA-DIM-001", QaSeverity.CRITICAL,
                          f"{d.id}: OCCT-drawn extent {drawn} mm disagrees with overall dimension {c.text}", [d.id])
        else:
            polys = rendered.lines[d.view_id]["visible"] + rendered.lines[d.view_id]["hidden"]
            if c.kind == CandidateKind.PCD:
                polys = polys + [_circle_polys(a.center, a.radius) for a in cd.annotations
                                 if a.view_id == d.view_id and a.kind == AnnotationKind.PITCH_CIRCLE]
            gap = _dist_to_polys(d.leader[0], polys)
            if gap > 0.3:
                R.add("QA-DIM-001", QaSeverity.CRITICAL,
                      f"{d.id} ({d.text.splitlines()[0]}): leader tip is {gap:.2f} mm from any drawn geometry",
                      [d.id])
    R.check("QA-DIM-002")
    selected = {s.candidate_id for s in plan.dimension_selections}
    for sid in sorted(selected - set(placed)):
        R.add("QA-DIM-002", QaSeverity.CRITICAL, f"planned dimension {sid} was not placed", [sid])
    if plan.dimensions.overall:
        covered_axes = set()
        for d in cd.dimensions:
            c = cands[d.id]
            if c.role == CandidateRole.OVERALL:
                covered_axes.add(d.id.rsplit("-", 1)[-1])
        missing = {f"DIM-OVERALL-{a}" for a in "XYZ"} - {f"DIM-OVERALL-{a}" for a in covered_axes}
        for m in sorted(missing):
            if m in cands:
                R.add("QA-DIM-002", QaSeverity.MAJOR, f"overall dimension {m} is not shown in any selected view", [m])
    if plan.dimensions.holes and plan.annotations.hole_callouts:
        called = {fid for d in cd.dimensions if cands[d.id].kind == CandidateKind.HOLE_CALLOUT
                  for fid in d.feature_ids}
        for h in ir.features:
            if h.type == FeatureType.HOLE and h.id not in called:
                R.add("QA-ANN-003", QaSeverity.MAJOR, f"hole {h.id} (Ø{h.diameter:g}) has no callout", [h.id])
    R.check("QA-DIM-003")
    for did in sorted({x for x in placed if placed.count(x) > 1}):
        R.add("QA-DIM-003", QaSeverity.CRITICAL, f"dimension {did} placed more than once", [did])
    R.check("QA-DIM-004")
    from drawing_planner.baseline import remove_redundant  # same rule the planner used

    _, redundant = remove_redundant([cands[d.id] for d in cd.dimensions if d.id in cands])
    for c in redundant:
        R.add("QA-DIM-004", QaSeverity.MAJOR, f"{c.id} ({c.text}) closes a dimension chain (redundant)", [c.id])
    R.check("QA-DIM-005")
    boxes = [(d.id, d.text_bbox) for d in cd.dimensions]
    for i, (a, ba) in enumerate(boxes):
        for b, bb in boxes[i + 1:]:
            if ba.intersects(bb, clearance=0.5):
                R.add("QA-DIM-005", QaSeverity.MAJOR, f"texts of {a} and {b} overlap", [a, b], ba.union(bb),
                      INCREASE_TIER_GAP)
        for vid, gb in geo_bbox.items():
            if gb is not None and vid != next(d.view_id for d in cd.dimensions if d.id == a) and ba.intersects(gb):
                R.add("QA-DIM-005", QaSeverity.MAJOR, f"text of {a} overlaps view {vid}", [a, vid], ba, REDUCE_SCALE)

    # ---------------------------------------------------------------- annotations / text / title block
    R.check("QA-ANN-001")
    if plan.annotations.center_marks:
        marked = {fid for a in cd.annotations if a.kind == AnnotationKind.CENTER_MARK for fid in a.feature_ids}
        centres = [(a.view_id, a.center) for a in cd.annotations if a.kind == AnnotationKind.CENTER_MARK]
        for h in [f for f in ir.features if f.type == FeatureType.HOLE]:
            seen = [v for v in cd.views if not v.pictorial and not v.detail_of
                    and abs(sum(a * b for a, b in zip(v.eye, h.axis.direction))) > 1 - 1e-6]
            if not seen or h.id in marked:
                continue
            ok = False
            for v in seen:  # a coincident mark (e.g. a concentric boss) also counts
                q = [h.axis.origin[k] - v.model_center[k] for k in range(3)]
                x = v.sheet_center[0] + v.scale_factor * sum(q[k] * v.x_axis[k] for k in range(3))
                y = v.sheet_center[1] + v.scale_factor * sum(q[k] * v.y_axis[k] for k in range(3))
                ok = ok or any(vid == v.id and math.hypot(c[0] - x, c[1] - y) < 0.01 for vid, c in centres)
            if not ok:
                R.add("QA-ANN-001", QaSeverity.MAJOR, f"hole {h.id} has no center mark in its circular view", [h.id])
    R.check("QA-TXT-001")
    for d in cd.dimensions:
        if d.text_height < MIN_TEXT:
            R.add("QA-TXT-001", QaSeverity.MAJOR, f"{d.id} text height {d.text_height} mm < {MIN_TEXT} mm", [d.id])
    R.check("QA-TB-001")
    info = plan.engineering_information
    tb_map = {  # title field -> engineering fields that may legitimately fill it
        "MATERIAL": ("material",), "GENERAL_TOL": ("general_tolerance",), "SURFACE_FINISH": ("surface_finish",),
        "LINEAR_TOL": ("linear_tolerance", "general_tolerance"),
        "ANGULAR_TOL": ("angular_tolerance", "general_tolerance"), "FINISH": ("coating", "heat_treatment"),
    }
    for f in cd.title_fields:
        if f.label in tb_map and f.value not in ("UNSPECIFIED", ""):
            supplied = {getattr(info, n).value for n in tb_map[f.label] if getattr(info, n).status == "SPECIFIED"}
            if not supplied or not all(part.strip() in supplied for part in f.value.split(",")):
                R.add("QA-TB-001", QaSeverity.CRITICAL, f"title block {f.label} shows a value nobody supplied", [f.label])
    if plan.manufacturing.deburr_break_sharp_edges is False and any(
            f.label == "EDGES" and f.value for f in cd.title_fields):
        R.add("QA-TB-001", QaSeverity.CRITICAL, "edge-treatment note printed although the user did not request it",
              ["EDGES"])

    _pmi_checks(R, plan, cd, geo_bbox)
    _datum_and_note_checks(R, plan, ir, cd)

    crit = sum(i.severity == QaSeverity.CRITICAL for i in R.issues)
    return QaReport(
        iteration=iteration, passed=crit == 0, critical=crit,
        major=sum(i.severity == QaSeverity.MAJOR for i in R.issues),
        minor=sum(i.severity == QaSeverity.MINOR for i in R.issues),
        checks_run=sorted(set(R.checks)), issues=R.issues,
    )


def _pmi_checks(R: _Report, plan: DrawingPlan, cd: CompiledDrawing, geo_bbox: dict) -> None:
    """User-supplied manufacturing annotations: every one is on the sheet exactly as supplied,
    and none of them collides with other drawing content."""
    m = plan.manufacturing
    R.check("QA-PMI-004")
    # the printed tolerance of every frame is the planned value (no rounding to the drawing's decimals)
    printed = [(fs.cells[0].symbol, fs.cells[1].text) for d in [*cd.dimensions, *cd.pmi] for fs in d.frames
               if len(fs.cells) > 1]
    for i, fr in enumerate(m.frames, 1):
        ok = False
        for sym, text in printed:
            try:
                ok = ok or (sym == fr.characteristic.value and abs(float(text) - fr.tolerance) < 1e-9)
            except (TypeError, ValueError):
                continue
        if not ok:
            R.add("QA-PMI-004", QaSeverity.CRITICAL,
                  f"frame {i} ({fr.characteristic.value} {fr.tolerance:g}) is not printed with its value")
    R.check("QA-PMI-001")
    for note in cd.notes:
        if note.startswith("UNPLACED:"):
            R.add("QA-PMI-001", QaSeverity.CRITICAL, f"user annotation not shown: {note[9:].strip()}")
        elif note.startswith("CROWDED:"):
            R.add("QA-PMI-001", QaSeverity.MAJOR, note[8:].strip(), repair=REDUCE_SCALE)
    R.check("QA-PMI-002")
    shown_datums = [d.datum for d in cd.dimensions if d.datum] + [p.datum for p in cd.pmi if p.datum]
    for d in m.datums:
        n = shown_datums.count(d.letter)
        if n != 1:
            R.add("QA-PMI-002", QaSeverity.CRITICAL, f"datum {d.letter} is shown {n} times (expected once)", [d.letter])
    for letter in sorted(set(shown_datums) - {d.letter for d in m.datums}):
        R.add("QA-PMI-002", QaSeverity.CRITICAL, f"datum {letter} is on the sheet but was never defined", [letter])
    frames = [f for d in cd.dimensions for f in d.frames] + [f for p in cd.pmi for f in p.frames]
    if len(frames) != len(m.frames):
        R.add("QA-PMI-002", QaSeverity.CRITICAL,
              f"{len(frames)} feature control frames on the sheet, {len(m.frames)} supplied")
    defined = {d.letter for d in m.datums}
    for fr in frames:
        for cell in fr.cells[2:]:
            if cell.text not in defined:
                R.add("QA-PMI-002", QaSeverity.CRITICAL, f"frame references undefined datum {cell.text}")
    tol = {d.id for d in cd.dimensions if d.tolerance is not None}
    for t in m.tolerances:
        if t.candidate_id not in tol:
            R.add("QA-PMI-002", QaSeverity.CRITICAL, f"tolerance on {t.candidate_id} is not shown", [t.candidate_id])
    insp = {d.id for d in cd.dimensions if d.inspection}
    for cid in m.inspection_dimensions:
        if cid not in insp:
            R.add("QA-PMI-002", QaSeverity.CRITICAL, f"inspection mark on {cid} is not shown", [cid])
    basic = {d.id for d in cd.dimensions if d.basic}
    for cid in m.basic_dimensions:
        if cid not in basic:
            R.add("QA-PMI-002", QaSeverity.CRITICAL, f"basic (TED) frame on {cid} is not shown", [cid])
    marks = sum(1 for p in cd.pmi if p.kind == "SURFACE_FINISH") + sum(1 for d in cd.dimensions if d.finish)
    if marks != len(m.surface_finish_marks):
        R.add("QA-PMI-002", QaSeverity.CRITICAL,
              f"{marks} surface texture symbols on the sheet, {len(m.surface_finish_marks)} supplied")
    R.check("QA-PMI-003")
    items = [(f"{d.id} text", d.view_id, d.text_bbox) for d in cd.dimensions]
    items += [(f"{d.id} frames/datum", d.view_id, d.extra_bbox) for d in cd.dimensions if d.extra_bbox]
    items += [(p.id, p.view_id, p.bbox) for p in cd.pmi]
    annotated = {name for name, _, _ in items[len(cd.dimensions):]}
    for i, (a, va, ba) in enumerate(items):
        for b, vb, bb in items[i + 1:]:
            if (a in annotated or b in annotated) and a.split(" ")[0] != b.split(" ")[0] and ba.intersects(bb, 0.3):
                R.add("QA-PMI-003", QaSeverity.MAJOR, f"{a} overlaps {b}", [a, b], ba.union(bb), REDUCE_SCALE)
        if a in annotated:
            for vid, gb in geo_bbox.items():
                if gb is not None and vid != va and ba.intersects(gb, 0.5):
                    R.add("QA-PMI-003", QaSeverity.MAJOR, f"{a} overlaps view {vid}", [a, vid], ba, REDUCE_SCALE)


_RULE_CHECK = {"R3": "QA-DAT-003", "R5/R7": "QA-DAT-005", "R7": "QA-DAT-007", "R8": "QA-DAT-008",
               "R9": "QA-DAT-009", "MEAS": "QA-TOL-001"}


def _datum_and_note_checks(R: _Report, plan: DrawingPlan, ir: GeometryIR, cd: CompiledDrawing) -> None:
    """Datum-scheme rules (see drawing_planner.datum_rules) and unresolved note placeholders.
    Findings are reported, never auto-corrected: the user owns the datum scheme."""
    from drawing_compiler.notes import build_notes, placeholders
    from drawing_planner.datum_rules import check_datum_scheme

    for cid in _RULE_CHECK.values():
        R.check(cid)
    for f in check_datum_scheme(ir, plan.manufacturing, plan.general_notes.process):
        R.add(_RULE_CHECK[f.rule], QaSeverity(f.severity), f"rule {f.rule[1:] if f.rule[0] == 'R' else ''}"
              f"{': ' if f.rule[0] == 'R' else ''}{f.message}", f.refs)
    R.check("QA-NOTE-001")
    if plan.general_notes.enabled:  # check the unwrapped notes (a placeholder may wrap across lines)
        notes, bullets, summary = build_notes(plan, ir)
        missing = placeholders(notes + [summary])
    else:
        missing = placeholders(cd.sheet_notes)
    if missing:
        uniq = list(dict.fromkeys(missing))
        R.add("QA-NOTE-001", QaSeverity.MAJOR,
              f"{len(uniq)} drawing-note values not supplied (printed as placeholders): " + ", ".join(uniq)[:600])
