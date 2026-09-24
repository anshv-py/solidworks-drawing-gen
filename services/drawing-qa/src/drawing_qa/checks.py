"""Deterministic drawing QA.

Several checks compare two *independent* computations: the compiler's analytic projection of
GeometryIR, and OCCT's hidden-line-removal output of the actual B-Rep. Disagreement means the
drawing does not show what the plan claims (wrong orientation, wrong extent, leader pointing
at nothing), so those checks are critical.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from drawing_schema import ISO_5455_SCALES, DrawingPlan, ProjectionMethod, ViewOrientation
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
        box = d.text_bbox
        for p in pts:
            box = box.union(Rect(x0=p[0], y0=p[1], x1=p[0], y1=p[1]))
        if not box.inside(cd.frame):
            R.add("QA-SHEET-002", QaSeverity.CRITICAL, f"dimension {d.id} ({d.text}) extends outside the frame",
                  [d.id], box, REDUCE_SCALE)
    R.check("QA-SHEET-003")
    strip = Rect(x0=cd.frame.x0, y0=cd.frame.y0, x1=cd.frame.x1, y1=cd.title_block.y1)
    for vid, bb in geo_bbox.items():
        if bb is not None and bb.intersects(strip):
            R.add("QA-SHEET-003", QaSeverity.CRITICAL, f"view {vid} collides with the title block / notes area",
                  [vid], bb, REDUCE_SCALE)
    for d in cd.dimensions:
        if d.text_bbox.intersects(strip):
            R.add("QA-SHEET-003", QaSeverity.CRITICAL, f"dimension {d.id} text collides with the title block",
                  [d.id], d.text_bbox, REDUCE_SCALE)

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
        if v.pictorial or bb is None:
            continue
        # HLR extents (OCCT) must equal the GeometryIR bounding box projected by the compiler
        tol = 0.05 * v.scale_factor + 0.01
        if abs(bb.w - v.outline.w) > tol or abs(bb.h - v.outline.h) > tol:
            R.add("QA-VIEW-002", QaSeverity.CRITICAL,
                  f"view {v.id}: drawn extent {bb.w / v.scale_factor:.3f} x {bb.h / v.scale_factor:.3f} mm "
                  f"differs from GeometryIR {v.outline.w / v.scale_factor:.3f} x {v.outline.h / v.scale_factor:.3f} mm",
                  [v.id], bb)
    R.check("QA-VIEW-003")
    front = next((v for v in cd.views if v.orientation == ViewOrientation.FRONT), None)
    if front is not None:
        first = cd.projection_method == ProjectionMethod.FIRST_ANGLE
        expect = {  # orientation -> (axis, sign) of offset from FRONT
            ViewOrientation.TOP: ("y", -1 if first else 1), ViewOrientation.BOTTOM: ("y", 1 if first else -1),
            ViewOrientation.RIGHT: ("x", -1 if first else 1), ViewOrientation.LEFT: ("x", 1 if first else -1),
        }
        fx, fy = front.sheet_center
        for v in cd.views:
            if v.orientation not in expect:
                continue
            axis, sign = expect[v.orientation]
            dx, dy = v.sheet_center[0] - fx, v.sheet_center[1] - fy
            along, across = (dy, dx) if axis == "y" else (dx, dy)
            if along * sign <= 0 or abs(across) > 1e-6:
                R.add("QA-VIEW-003", QaSeverity.CRITICAL,
                      f"{v.id} is not placed per {cd.projection_method.value} projection relative to FRONT", [v.id])
    R.check("QA-VIEW-004")
    for v in cd.views:
        if v.scale not in ISO_5455_SCALES:
            R.add("QA-VIEW-004", QaSeverity.MAJOR, f"{v.id} scale {v.scale} is not an ISO 5455 scale", [v.id])
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
            seen = [v for v in cd.views if not v.pictorial and abs(sum(a * b for a, b in zip(v.eye, h.axis.direction))) > 1 - 1e-6]
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
    tb_map = {"MATERIAL": "material", "GENERAL TOL.": "general_tolerance", "SURFACE FINISH": "surface_finish"}
    for f in cd.title_fields:
        if f.label in tb_map:
            src = getattr(info, tb_map[f.label])
            if f.value != "UNSPECIFIED" and src.status != "SPECIFIED":
                R.add("QA-TB-001", QaSeverity.CRITICAL, f"title block {f.label} shows a value nobody supplied", [f.label])

    crit = sum(i.severity == QaSeverity.CRITICAL for i in R.issues)
    return QaReport(
        iteration=iteration, passed=crit == 0, critical=crit,
        major=sum(i.severity == QaSeverity.MAJOR for i in R.issues),
        minor=sum(i.severity == QaSeverity.MINOR for i in R.issues),
        checks_run=sorted(set(R.checks)), issues=R.issues,
    )
