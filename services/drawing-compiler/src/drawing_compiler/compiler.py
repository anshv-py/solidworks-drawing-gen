"""DrawingPlan + candidates + GeometryIR -> CompiledDrawing (deterministic sheet layout).

Sheet format (matches the SolidWorks-style references)
------------------------------------------------------
* 10 mm margins, ISO 5457 zone grid (A4 6x4, A3 8x6, A2 12x8, A1 16x12, A0 24x16; columns
  numbered right-to-left, rows lettered top-to-bottom).
* 180 x 55 mm title block in the bottom-right corner (standard template grid), a numbered
  "Note:" block directly above it, and a revision table in the top-right corner when the user
  supplied revisions. These are obstacles for the view layout.

Views
-----
* Orthographic views on a grid relative to FRONT per projection method; views in a column share
  the x projection, views in a row the y projection.
* Envelope = part outline + dimension tiers (variable height: a tier grows when a dimension
  carries a feature control frame / datum) + a leader-note column + space for face annotations.
* Scale: the user's ``sheet.scale``, or (AUTO) the largest scale of the chosen series
  (``sheet.scale_system``: ISO 5455 only, or with intermediate steps) for which the grid fits the sheet without touching an obstacle (several anchor positions are tried). The
  undimensioned pictorial view goes top-right at ``sheet.pictorial_scale``, or (AUTO) the smallest
  scale that draws it larger than every orthographic view (one step up at most).

Manufacturing annotations (user-supplied only) are attached deterministically:
hole / pattern → under its callout; boss → at its Ø dimension; face → leader from the view in
which the face is seen edge-on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from drawing_schema import (
    scale_series,
    PICTORIAL,
    DisplayStyle,
    DrawingPlan,
    ProjectionMethod,
    SheetOrientation,
    SheetSize,
    ViewOrientation,
)
from drawing_schema.candidates import CandidateKind, CandidateRole, DimensionCandidate, ViewRule
from drawing_schema.compiled import (
    Stamp,
    AnnotationKind,
    AnnotationOp,
    CompiledDrawing,
    CompiledView,
    DimensionOp,
    DimensionOpKind,
    FrameCell,
    FrameSpec,
    PmiKind,
    PmiOp,
    Rect,
    TitleBlockField,
    ToleranceText,
)
from drawing_schema.frames import Frame, dot, view_frame
from drawing_compiler.notes import build_notes
from drawing_schema.pmi import FeatureControlFrame, ToleranceKind
from geometry_schema import FeatureType, GeometryIR, SurfaceType

TEXT_H = 3.5  # mm, ISO 3098 on A3
TOL_H = 2.5  # stacked tolerance text height
CHAR_W = 0.8  # conservative width factor per character (Arial-metric sans; layout/QA boxes)
FIRST_TIER = 10.0
TIER_GAP = 8.0
STAMP_H = 9.0  # release stamp band height
VIEW_GAP = 12.0
NOTE_GAP = 2.0
CENTER_EXT = 3.0
MARGIN = 10.0
TITLE_W, TITLE_H = 180.0, 55.0
FRAME_H = 7.0
DATUM_BOX = 6.0
DATUM_DROP = 5.0  # leader between datum triangle and box
FACE_OFFSET = 6.0
PICT_LABEL_SPACE = 7.0  # 'SCALE 1:5' under a pictorial view drawn at its own scale
NOTE_LINE = 3.8  # 2.5 mm text (legible on A3) at 1.5x pitch
NOTE_TEXT_H = 2.5
SF_HEIGHT = 11.0  # ISO 1302 symbol (long leg 10 mm) + clearance
SECTION_STROKE = 6.0  # thick end of the cutting plane (ISO 128-44)
SECTION_END = 16.0  # room beyond the dimensions for the stroke, arrow and letter
SECTION_LABEL = 8.0  # room below a section view for its A-A designation
FINISH_TIP_X = 3.0  # symbol point from the left of its box (the short leg reaches 2.9 mm left)


def finish_width(text: str) -> float:
    """Upright ISO 1302 symbol: short leg, long leg (2*5/tan60) and the line over the Ra text."""
    return FINISH_TIP_X + 5.8 + len(text) * CHAR_W * TOL_H + 2.0
TIP_FRACTIONS = (0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 0.1, 0.9, 0.03, 0.97)

ZONES = {  # ISO 5457 recommended grids (landscape: columns x rows)
    SheetSize.A4: (6, 4), SheetSize.A3: (8, 6), SheetSize.A2: (12, 8), SheetSize.A1: (16, 12),
    SheetSize.A0: (24, 16),
}


def _segment_hits(a, b, r: Rect, skip: float = 0.0, clearance: float = 0.8) -> bool:
    """Does segment a-b (ignoring its first ``skip`` mm) pass through rect r (+clearance)?"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    if n < 1e-9:
        return False
    t0, t1 = min(skip / n, 1.0), 1.0
    for p, q in ((-dx, a[0] - (r.x0 - clearance)), (dx, (r.x1 + clearance) - a[0]),
                 (-dy, a[1] - (r.y0 - clearance)), (dy, (r.y1 + clearance) - a[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _segment_boxes(a, b, size: float = 2.0) -> list[Rect]:
    """Small boxes covering a segment (so later placements keep clear of a drawn leader)."""
    n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / size))
    out = []
    for k in range(n + 1):
        x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
        out.append(Rect(x0=x - 0.3, y0=y - 0.3, x1=x + 0.3, y1=y + 0.3))
    return out


def _wrap(text: str, first: str, rest: str, width: float = TITLE_W) -> list[str]:
    """Word-wrap a note to a notes column of the given width (2.5 mm text)."""
    max_chars = int((width - 6.0) / (CHAR_W * NOTE_TEXT_H))
    out, cur = [], first
    for w in text.split(" "):
        if len(cur) + len(w) > max_chars and cur.strip() not in ("", first.strip()):
            out.append(cur.rstrip())
            cur = rest
        cur += w + " "
    return out + [cur.rstrip()]


class LayoutError(Exception):
    pass


@dataclass
class CompileOptions:
    max_scale: str | None = None  # QA repair: never exceed this scale
    tier_gap: float = TIER_GAP
    generated_on: date | None = None
    notes: list[str] = field(default_factory=list)
    stamp: str | None = None  # release stamp text (compliance gate), printed above the title-block column


def scale_factor(s: str) -> float:
    a, b = s.split(":")
    return float(a) / float(b)


def text_width(text: str, h: float = TEXT_H) -> float:
    return max(len(line) for line in text.split("\n")) * CHAR_W * h


def text_height(text: str, h: float = TEXT_H) -> float:
    n = text.count("\n") + 1
    return n * h + (n - 1) * h * 0.6


def fmt(v: float, dp: int, trailing_zeros: bool = True) -> str:
    s = f"{v:.{dp}f}"
    if s.startswith("-") and float(s) == 0:
        s = s[1:]
    if trailing_zeros or "." not in s:
        return s
    return s.rstrip("0").rstrip(".")


def decimals_needed(v: float, limit: int = 4) -> int:
    """Decimals that print ``v`` without rounding (up to ``limit``)."""
    for d in range(limit + 1):
        if abs(round(v, d) - v) < 1e-9:
            return d
    return limit


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _r(p) -> tuple[float, float]:
    return (round(p[0], 4), round(p[1], 4))


# grid cell (row, col) relative to FRONT at (1, 1); rows grow downward
_FIRST = {
    ViewOrientation.FRONT: (1, 1), ViewOrientation.TOP: (2, 1), ViewOrientation.BOTTOM: (0, 1),
    ViewOrientation.RIGHT: (1, 0), ViewOrientation.LEFT: (1, 2), ViewOrientation.BACK: (1, 3),
}
_THIRD = {
    ViewOrientation.FRONT: (1, 1), ViewOrientation.TOP: (0, 1), ViewOrientation.BOTTOM: (2, 1),
    ViewOrientation.RIGHT: (1, 2), ViewOrientation.LEFT: (1, 0), ViewOrientation.BACK: (1, 3),
}


@dataclass
class _Attach:
    """User annotations attached to a dimension or callout."""

    frames: list[FrameSpec] = field(default_factory=list)
    datum: str | None = None
    finish: str | None = None  # ISO 1302 symbol text for a cylindrical feature (e.g. "Ra 0.8")

    @property
    def empty(self) -> bool:
        return not self.frames and self.datum is None and self.finish is None


@dataclass
class _Note:
    """Something drawn in a view's leader-note column."""

    id: str
    text: str
    value: float
    feature_ids: list[str]
    cand: DimensionCandidate | None = None
    face_point: tuple | None = None  # model point for face notes
    attach: _Attach = field(default_factory=_Attach)

    def height(self) -> float:
        h = text_height(self.text)
        if self.attach.frames:
            h += 1.0 + FRAME_H * len(self.attach.frames)
        if self.attach.datum:
            h += DATUM_DROP + DATUM_BOX
        if self.attach.finish:
            h += SF_HEIGHT
        return h

    def width(self) -> float:
        w = text_width(self.text) + 2
        for f in self.attach.frames:
            w = max(w, f.width + 2)
        if self.attach.finish:
            w = max(w, finish_width(self.attach.finish) + 2)
        return w


@dataclass
class _FaceGroup:
    face_id: str
    point: tuple  # model point on the face
    normal: tuple
    frames: list[FrameSpec] = field(default_factory=list)
    datum: str | None = None
    finish: list[float] = field(default_factory=list)  # Ra values

    def box_size(self) -> tuple[float, float]:
        w = max([f.width for f in self.frames] + [DATUM_BOX if self.datum else 0.0])
        h = FRAME_H * len(self.frames) + ((DATUM_DROP + DATUM_BOX) if self.datum and self.frames else
                                          DATUM_BOX if self.datum else 0.0)
        return w, h


@dataclass
class _ViewCtx:
    id: str
    orientation: ViewOrientation
    frame: Frame
    pictorial: bool
    style: DisplayStyle
    half: tuple[float, float, float, float] = (0, 0, 0, 0)  # model extents about center (u0,u1,v0,v1)
    dims: list = field(default_factory=list)  # (candidate, horizontal, p1, p2)
    notes: list[_Note] = field(default_factory=list)
    groups: list[_FaceGroup] = field(default_factory=list)
    margins: dict = field(default_factory=dict)
    tiers: dict = field(default_factory=dict)  # candidate id -> tier index
    tier_off: dict = field(default_factory=dict)  # side -> list of tier offsets
    side_of: dict = field(default_factory=dict)
    group_side: dict = field(default_factory=dict)
    group_levels: dict = field(default_factory=dict)  # side -> (level step, number of levels)
    tier_margin: dict = field(default_factory=dict)
    notes_x: float = 0.0
    cell: tuple[int, int] = (0, 0)
    section: tuple | None = None  # (letter, plane point, normal toward the removed half): drawn as a section
    trace: tuple | None = None  # (letter, plane point, normal): this view shows the cutting plane
    trace_base: dict = field(default_factory=dict)  # side -> margin before the cutting-plane ends


class Compiler:
    def __init__(self, plan: DrawingPlan, candidates: list[DimensionCandidate], ir: GeometryIR,
                 options: CompileOptions | None = None) -> None:
        self.plan, self.ir = plan, ir
        self.opt = options or CompileOptions()
        self.cands = {c.id: c for c in candidates}
        self.features = {f.id: f for f in ir.features}
        self.faces = {f.id: f for f in ir.faces}
        self.dp = plan.dimensions.decimal_places
        self.tz = plan.dimensions.trailing_zeros
        self.m = plan.manufacturing
        bb = ir.bounding_box
        self.center = tuple((bb.min[i] + bb.max[i]) / 2 for i in range(3))
        self.corners = [
            (x, y, z) for x in (bb.min[0], bb.max[0]) for y in (bb.min[1], bb.max[1]) for z in (bb.min[2], bb.max[2])
        ]
        w, h = plan.sheet.dimensions_mm()
        self.sheet_w, self.sheet_h = w, h
        cols, rows = ZONES[plan.sheet.size]
        self.zones = (cols, rows) if plan.sheet.orientation == SheetOrientation.LANDSCAPE else (rows, cols)
        self.frame_rect = Rect(x0=MARGIN, y0=MARGIN, x1=w - MARGIN, y1=h - MARGIN)
        tb_w = min(TITLE_W, self.frame_rect.w)
        self.title_rect = Rect(x0=self.frame_rect.x1 - tb_w, y0=self.frame_rect.y0,
                               x1=self.frame_rect.x1, y1=self.frame_rect.y0 + TITLE_H)
        self.revision_rows = [[r.revision, r.description, r.date, r.approved_by] for r in self.m.revisions]
        self.revision_rect = None
        if self.revision_rows:
            rh = 6.0 * (len(self.revision_rows) + 2)  # title + header + entries
            self.revision_rect = Rect(x0=self.frame_rect.x1 - tb_w, y0=self.frame_rect.y1 - rh,
                                      x1=self.frame_rect.x1, y1=self.frame_rect.y1)
        self.area = Rect(x0=self.frame_rect.x0 + 4, y0=self.frame_rect.y0 + 4,
                         x1=self.frame_rect.x1 - 4, y1=self.frame_rect.y1 - 4)
        self.notes_variants = ["column", "band", "beside"] if self._sheet_note_texts() else ["column"]
        if not self._set_notes(self.notes_variants[0]):
            self._set_notes("band")
        self.pict_scale: tuple[str, float] | None = None
        self.views = self._views()

    # ------------------------------------------------------------------ formatting helpers
    def f(self, v: float) -> str:
        return fmt(v, self.dp, self.tz)

    def ft(self, v: float) -> str:
        """A tolerance value: the drawing's decimals, or more when the value needs them (0.005 never
        prints as 0.01)."""
        return fmt(v, max(self.dp, decimals_needed(v)), self.tz)

    def _frame_spec(self, fr: FeatureControlFrame) -> FrameSpec:
        cells = [FrameCell(symbol=fr.characteristic.value, width=FRAME_H)]
        tol = self.ft(fr.tolerance)
        w = len(tol) * CHAR_W * TEXT_H + 3.0 + (TEXT_H if fr.diameter_zone else 0.0) + (
            4.0 if fr.material_condition else 0.0)
        cells.append(FrameCell(text=tol, diameter=fr.diameter_zone,
                               modifier=fr.material_condition.value if fr.material_condition else None,
                               width=round(w, 2)))
        for d in fr.datums:
            cells.append(FrameCell(text=d.letter, modifier=d.material_condition.value if d.material_condition else None,
                                   width=FRAME_H + (4.0 if d.material_condition else 0.0)))
        return FrameSpec(cells=cells, height=FRAME_H)

    def _tolerance(self, cand: DimensionCandidate) -> ToleranceText | None:
        t = next((t for t in self.m.tolerances if t.candidate_id == cand.id), None)
        if t is None:
            return None
        if t.kind == ToleranceKind.SYMMETRIC:
            return ToleranceText(kind=t.kind.value, upper=f"±{self.ft(t.upper)}")

        def dev(x: float) -> str:
            return self.f(0.0) if abs(x) < 1e-12 else (f"+{self.ft(x)}" if x > 0 else f"-{self.ft(-x)}")

        if t.kind == ToleranceKind.DEVIATION:
            return ToleranceText(kind=t.kind.value, upper=dev(t.upper), lower=dev(t.lower))
        if t.kind == ToleranceKind.FIT:
            # ISO 286 deviations are printed to the micrometre whatever the drawing's decimals
            def fit_dev(x: float) -> str:
                return "0" if abs(x) < 1e-12 else f"{x:+.3f}"

            return ToleranceText(kind=t.kind.value, upper=fit_dev(t.upper), lower=fit_dev(t.lower), fit=t.fit or "")
        prefix = "Ø" if cand.text.lstrip("0123456789X ").startswith("Ø") else ""
        return ToleranceText(kind=t.kind.value, upper=prefix + self.ft(cand.value + t.upper),
                             lower=prefix + self.ft(cand.value + t.lower))

    def _label_width(self, cand: DimensionCandidate) -> float:
        tol = self._tolerance(cand)
        w = text_width(cand.text)
        if tol is not None:
            if tol.kind == "LIMITS":
                w = max(len(tol.upper), len(tol.lower)) * CHAR_W * TEXT_H
            elif tol.kind == "FIT":
                w += text_width(" " + tol.fit) + 1.8 + max(len(tol.upper), len(tol.lower)) * CHAR_W * TOL_H
            else:
                w += 1.0 + max(len(tol.upper), len(tol.lower)) * CHAR_W * (TOL_H if tol.lower else TEXT_H)
        framed = cand.id in self.m.inspection_dimensions or cand.id in self.m.basic_dimensions
        return w + (3.0 if framed else 0.0)

    def _label_height(self, cand: DimensionCandidate) -> float:
        tol = self._tolerance(cand)
        return TEXT_H if tol is None or tol.kind == "SYMMETRIC" else 2 * TOL_H + 0.5

    def _sheet_note_texts(self) -> list[tuple[str, str, str]]:
        """(text, first-line prefix, continuation prefix) for every note, bullet and the summary."""
        if self.plan.general_notes.enabled:
            notes, bullets, summary = build_notes(self.plan, self.ir)
        else:
            notes = ["ALL DIMENSIONS ARE IN MM"] + [n.strip() for n in self.m.notes if n.strip()]
            bullets, summary = [], ""
        out = [(" ".join(t.split()), f"{i}) ", "    ") for i, t in enumerate(notes, 1)]
        if bullets:
            out.append(("WHAT THE SUPPLIER MUST NOT ASSUME:", "", ""))
            out += [(b, "- ", "   ") for b in bullets]
        if summary:
            out.append((summary, "", "  "))
        return out

    def _note_blocks(self, width: float) -> list[list[str]]:
        return [_wrap(t, a, b, width) for t, a, b in self._sheet_note_texts()]

    def _set_notes(self, variant: str) -> bool:
        """Place the notes block. 'column' (as in the references): one 180 mm column directly above
        the title block. 'band': two columns side by side, about half as tall, for parts whose views
        need the width. 'beside': along the bottom edge left of the title block, for parts whose views
        need the height on the right. -> False if the notes do not fit on the sheet."""
        self.notes_variant = variant
        self.notes_split = None
        top_free = (self.revision_rect.y0 - 3 if self.revision_rect else self.frame_rect.y1)
        beside_w = self.title_rect.x0 - self.frame_rect.x0 - 6.0
        if variant == "beside" and beside_w < 120.0:
            return False  # too narrow (e.g. A4): the notes would wrap into a tall column
        blocks = self._note_blocks(self.title_rect.w if variant == "column" else beside_w if variant == "beside"
                                   else min(2 * TITLE_W, self.frame_rect.w) / 2)
        lines = [ln for b in blocks for ln in b]
        self.sheet_notes = lines
        self.notes_rect = None
        tr, fr = self.title_rect, self.frame_rect
        self.obstacles = []
        if not lines:
            self.obstacles.append(Rect(x0=tr.x0 - 3, y0=fr.y0, x1=fr.x1, y1=tr.y1 + 3))
        elif variant == "column":
            self.notes_rect = Rect(x0=tr.x0, y0=tr.y1 + 1.0, x1=tr.x1,
                                   y1=tr.y1 + 3.0 + (len(lines) + 1) * NOTE_LINE)
            self.obstacles.append(Rect(x0=tr.x0 - 3, y0=fr.y0, x1=fr.x1, y1=self.notes_rect.y1 + 3))
        elif variant == "beside":
            self.notes_rect = Rect(x0=fr.x0 + 3.0, y0=fr.y0 + 1.0, x1=tr.x0 - 3.0,
                                   y1=fr.y0 + 3.0 + (len(lines) + 1) * NOTE_LINE)
            self.obstacles.append(Rect(x0=tr.x0 - 3, y0=fr.y0, x1=fr.x1, y1=tr.y1 + 3))
            self.obstacles.append(Rect(x0=fr.x0, y0=fr.y0, x1=tr.x0, y1=self.notes_rect.y1 + 3))
        else:
            sizes = [len(b) for b in blocks]
            total = sum(sizes)
            k = min(range(1, len(blocks) + 1), key=lambda k: (max(sum(sizes[:k]), total - sum(sizes[:k])), -k))
            self.notes_split = sum(sizes[:k])
            rows = max(self.notes_split, total - self.notes_split)
            width = min(2 * TITLE_W, fr.w)
            self.notes_rect = Rect(x0=fr.x1 - width, y0=tr.y1 + 1.0, x1=fr.x1,
                                   y1=tr.y1 + 3.0 + (rows + 1) * NOTE_LINE)
            self.obstacles.append(Rect(x0=self.notes_rect.x0 - 3, y0=fr.y0, x1=fr.x1, y1=self.notes_rect.y1 + 3))
        self.stamp_rect = None
        if self.opt.stamp:
            # the stamp sits on top of the right-hand column (title block + notes); that column grows by it
            col = self.obstacles[0]
            self.stamp_rect = Rect(x0=tr.x0, y0=col.y1 - 2.0, x1=tr.x1, y1=col.y1 - 2.0 + STAMP_H)
            self.obstacles[0] = Rect(x0=col.x0, y0=col.y0, x1=col.x1, y1=self.stamp_rect.y1 + 3)
        if self.revision_rect:
            self.obstacles.append(Rect(x0=self.revision_rect.x0 - 3, y0=self.revision_rect.y0 - 3,
                                       x1=fr.x1, y1=fr.y1))
        if self.stamp_rect is not None and self.stamp_rect.y1 > top_free:
            return False
        return self.notes_rect is None or self.notes_rect.y1 <= top_free

    # ------------------------------------------------------------------ views & assignment
    def _views(self) -> list[_ViewCtx]:
        p = self.plan
        out: list[_ViewCtx] = []
        pv = p.primary_view
        pict_style = p.pictorial_style if p.pictorial_style != DisplayStyle.HIDDEN_LINES_VISIBLE else (
            DisplayStyle.HIDDEN_LINES_REMOVED)
        out.append(_ViewCtx(pv.id, pv.orientation, view_frame(pv.orientation, p.view_frame),
                            pv.orientation in PICTORIAL,
                            pict_style if pv.orientation in PICTORIAL else pv.display_style))
        for o in p.projected_views:
            out.append(_ViewCtx(f"V-{o.value}", o, view_frame(o, p.view_frame), False, p.orthographic_display_style))
        for v in out:
            us = [dot(_sub(c, self.center), v.frame.x) for c in self.corners]
            vs = [dot(_sub(c, self.center), v.frame.y) for c in self.corners]
            v.half = (min(us), max(us), min(vs), max(vs))
        by_id = {v.id: v for v in out}
        # RULES 1.3 / ISO 128-44: a full section drawn in place of its view, the plane shown in the parent
        for sec in p.sections:
            v, parent = by_id.get(sec.id), by_id.get(sec.parent_view_id)
            feat = self.features.get(sec.plane.through_feature_id or "")
            if sec.replaces is None or v is None or v.pictorial or parent is None or feat is None:
                self.opt.notes.append(f"UNPLACED: section {sec.label}-{sec.label}")
                continue
            cut = (sec.label, tuple(feat.axis.origin), tuple(v.frame.eye))
            v.section, v.style = cut, DisplayStyle.HIDDEN_LINES_REMOVED  # no hidden lines in sections
            parent.trace = cut
        dim_view: dict[str, _ViewCtx] = {}
        for sel in p.dimension_selections:
            c = self.cands.get(sel.candidate_id)
            v = by_id.get(sel.view_id)
            if c is None or v is None or v.pictorial:
                continue
            if c.kind in (CandidateKind.LINEAR, CandidateKind.DIAMETER):
                geo = self._linear_geometry(c, v)
                if geo is None:
                    self.opt.notes.append(f"{c.id}: not axis-aligned in {v.id}; skipped")
                    continue
                v.dims.append((c, *geo))
            else:
                v.notes.append(_Note(id=c.id, text=c.text, value=c.value, feature_ids=list(c.feature_ids), cand=c))
            dim_view[c.id] = v
        self._attach_pmi(out, dim_view)
        return out

    def _attach_pmi(self, views: list[_ViewCtx], dim_view: dict[str, _ViewCtx]) -> None:
        """Route user annotations to a callout / dimension / face group."""
        self.dim_attach: dict[str, _Attach] = {}
        groups: dict[str, _FaceGroup] = {}

        def owner_candidate(feature_id: str) -> str | None:
            feat = self.features.get(feature_id)
            if feat is None:
                return None
            ids = [feature_id]
            if feat.type == FeatureType.PATTERN:
                ids += list(feat.member_feature_ids)
            order = []
            if feat.type in (FeatureType.HOLE, FeatureType.PATTERN):
                order = [c for c in dim_view if c.startswith("DIM-CALLOUT") and set(ids) & set(self.cands[c].feature_ids)]
            elif feat.type == FeatureType.BOSS:
                order = [c for c in dim_view if c == f"DIM-DIA-{feature_id}"]
            elif feat.type in (FeatureType.SLOT, FeatureType.POCKET):
                order = [c for c in dim_view if c == f"DIM-W-{feature_id}"]
            return sorted(order)[0] if order else None

        def face_group(face_id: str) -> _FaceGroup | None:
            face = self.faces.get(face_id)
            if face is None or face.surface_type != SurfaceType.PLANE:
                return None
            if face_id not in groups:
                groups[face_id] = _FaceGroup(face_id=face_id, point=face.centroid, normal=face.surface.normal)
            return groups[face_id]

        def attach(target, frame: FrameSpec | None = None, datum: str | None = None, what: str = "") -> None:
            if target.feature_id:
                cid = owner_candidate(target.feature_id)
                if cid is None:
                    self.opt.notes.append(f"UNPLACED: {what} - its feature has no dimension/callout on the drawing")
                    return
                a = self.dim_attach.setdefault(cid, _Attach())
                if frame:
                    a.frames.append(frame)
                if datum:
                    a.datum = datum
            else:
                g = face_group(target.face_id)
                if g is None:
                    self.opt.notes.append(f"UNPLACED: {what} - face is not planar")
                    return
                if frame:
                    g.frames.append(frame)
                if datum:
                    g.datum = datum

        for d in self.m.datums:
            attach(d.target, datum=d.letter, what=f"datum {d.letter}")
        for i, fr in enumerate(self.m.frames, 1):
            attach(fr.target, frame=self._frame_spec(fr), what=f"frame {i} ({fr.characteristic.value})")
        for sf in self.m.surface_finish_marks:
            if sf.target.feature_id:
                # a hole / boss surface: the symbol goes with the feature's size callout (ISO 1302)
                cid = owner_candidate(sf.target.feature_id)
                a = self.dim_attach.setdefault(cid, _Attach()) if cid else None
                if a is None or a.finish is not None:
                    self.opt.notes.append(f"UNPLACED: surface finish Ra {sf.ra_um} on {sf.target.feature_id} - its "
                                          "feature has no size dimension / callout on the drawing")
                else:
                    a.finish = f"Ra {fmt(sf.ra_um, 2, False)}"
                continue
            g = face_group(sf.target.face_id) if sf.target.face_id else None
            if g is None:
                self.opt.notes.append(f"UNPLACED: surface finish Ra {sf.ra_um} - needs a planar face")
            else:
                g.finish.append(sf.ra_um)
        # linear dims / notes with attachments get them in place
        for v in views:
            for n in v.notes:
                if n.id in self.dim_attach:
                    n.attach = self.dim_attach[n.id]
        # face groups: the orthographic view that shows the face edge-on (longest edge wins)
        ortho = [v for v in views if not v.pictorial]
        for g in sorted(groups.values(), key=lambda g: g.face_id):
            best = None
            for v in ortho:
                if abs(dot(g.normal, v.frame.eye)) > 1e-6:
                    continue
                face = self.faces[g.face_id]
                length = self._face_extent_in_view(face, v)
                if best is None or length > best[0] + 1e-9:
                    best = (length, v)
            if best is None:
                self.opt.notes.append(f"UNPLACED: annotations on face {g.face_id} - no selected view shows it edge-on")
                continue
            best[1].groups.append(g)
        # feature notes go to the note column of a view that shows the target
        for i, fn in enumerate(self.m.feature_notes, 1):
            placed = False
            if fn.target.feature_id and fn.target.feature_id in self.features:
                cid = owner_candidate(fn.target.feature_id)
                v = dim_view.get(cid) if cid else None
                feat = self.features[fn.target.feature_id]
                face = self.faces.get(feat.face_ids[0]) if feat.face_ids else None
                if v is not None and face is not None and v in ortho:
                    v.notes.append(_Note(id=f"NOTE-{i}", text=fn.text.upper(), value=0.0,
                                         feature_ids=[feat.id], face_point=face.centroid))
                    placed = True
            elif fn.target.face_id in self.faces:
                face = self.faces[fn.target.face_id]
                for v in ortho:
                    if face.surface_type != SurfaceType.PLANE or abs(dot(face.surface.normal, v.frame.eye)) < 1e-6:
                        v.notes.append(_Note(id=f"NOTE-{i}", text=fn.text.upper(), value=0.0,
                                             feature_ids=[face.id], face_point=face.centroid))
                        placed = True
                        break
            if not placed:
                self.opt.notes.append(f"UNPLACED: note '{fn.text}'")

    def _face_extent_in_view(self, face, v: _ViewCtx) -> float:
        pts = []
        eids = set(face.edge_ids)
        for e in self.ir.edges:
            if e.id in eids:
                pts += [e.start, e.end]
        if not pts:
            return 0.0
        us = [dot(p, v.frame.x) for p in pts]
        ws = [dot(p, v.frame.y) for p in pts]
        return max(max(us) - min(us), max(ws) - min(ws))

    def _linear_geometry(self, c: DimensionCandidate, v: _ViewCtx):
        """-> (horizontal, p1_model, p2_model) or None."""
        f = v.frame
        if c.kind == CandidateKind.DIAMETER:
            ax = c.axis
            if abs(dot(ax, f.y)) > 1 - 1e-6:
                d = f.x
            elif abs(dot(ax, f.x)) > 1 - 1e-6:
                d = f.y
            else:
                return None
            p1, p2 = _add(c.center, _mul(d, -c.radius)), _add(c.center, _mul(d, c.radius))
        else:
            d, p1, p2 = c.direction, c.p1, c.p2
        if abs(dot(d, f.x)) > 1 - 1e-6:
            return True, p1, p2
        if abs(dot(d, f.y)) > 1 - 1e-6:
            return False, p1, p2
        return None

    # ------------------------------------------------------------------ per-scale envelopes
    def _uv(self, v: _ViewCtx, p) -> tuple[float, float]:
        q = _sub(p, self.center)
        return dot(q, v.frame.x), dot(q, v.frame.y)

    def _attach_extent(self, cid: str, horizontal: bool) -> float:
        """Extra outward space a dimension needs for its frames / datum."""
        a = self.dim_attach.get(cid)
        if a is None or a.empty:
            return 0.0
        if horizontal:
            return len(a.frames) * FRAME_H + (DATUM_DROP + DATUM_BOX if a.datum else 0.0) + 1.0 + (
                SF_HEIGHT if a.finish else 0.0)
        return max([fr.width for fr in a.frames] + [0.0]) + (DATUM_DROP + DATUM_BOX if a.datum else 0.0) + 2.0 + (
            finish_width(a.finish) + 2.0 if a.finish else 0.0)

    def _plan_view(self, v: _ViewCtx, s: float) -> None:
        """Assign dimension sides/tiers and compute envelope margins at scale s."""
        u0, u1, w0, w1 = (x * s for x in v.half)
        sides: dict[str, list] = {"top": [], "bottom": [], "left": [], "right": []}
        for c, horizontal, p1, p2 in v.dims:
            a1, b1 = self._uv(v, p1)
            a2, b2 = self._uv(v, p2)
            if horizontal:
                mid = (b1 + b2) / 2 * s
                side = "top" if mid > (w0 + w1) / 2 + 1e-6 else "bottom"
                span = (min(a1, a2) * s, max(a1, a2) * s)
            else:
                mid = (a1 + a2) / 2 * s
                side = "right" if mid > (u0 + u1) / 2 + 1e-6 else "left"
                span = (min(b1, b2) * s, max(b1, b2) * s)
            sides[side].append((c, span, horizontal))
        v.tiers, v.margins, v.side_of, v.tier_off = {}, {}, {}, {}
        overhang = {"top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0}
        for side, items in sides.items():
            tiers: list[list[tuple[float, float]]] = []
            extra: list[float] = []
            for c, span, horizontal in sorted(items, key=lambda it: (it[1][1] - it[1][0], it[0].priority, it[0].id)):
                tw = self._label_width(c) + 2
                a = self.dim_attach.get(c.id)
                if a and horizontal:
                    tw = max([tw] + [fr.width + 2 for fr in a.frames]
                             + ([finish_width(a.finish) + 2] if a.finish else []))
                lo, hi = span
                mid = (lo + hi) / 2
                occ = (min(lo, mid - tw / 2) - 1, max(hi, mid + tw / 2) + 1)
                ext = self._attach_extent(c.id, horizontal)
                for k, tier in enumerate(tiers):
                    if all(occ[1] <= a0 or occ[0] >= b0 for a0, b0 in tier):
                        tier.append(occ)
                        extra[k] = max(extra[k], ext)
                        v.tiers[c.id] = k
                        break
                else:
                    tiers.append([occ])
                    extra.append(ext)
                    v.tiers[c.id] = len(tiers) - 1
                v.side_of[c.id] = side
                # text longer than its dimension overhangs the view along the dimension line
                if horizontal:
                    overhang["left"] = max(overhang["left"], u0 - occ[0])
                    overhang["right"] = max(overhang["right"], occ[1] - u1)
                else:
                    overhang["bottom"] = max(overhang["bottom"], w0 - occ[0])
                    overhang["top"] = max(overhang["top"], occ[1] - w1)
            offs, off = [], FIRST_TIER
            for k in range(len(tiers)):
                offs.append(off)
                off += self.opt.tier_gap + extra[k]
            v.tier_off[side] = offs
            v.margins[side] = 0.0 if not tiers else offs[-1] + extra[-1] + TEXT_H + 2
        for side, o in overhang.items():
            v.margins[side] = max(v.margins[side], o)
        v.tier_margin = dict(v.margins)        # face annotation groups sit outside the tiers on the side their face normal points to
        v.group_side, v.group_levels = {}, {}
        per_side: dict[str, list[float]] = {}
        for g in v.groups:
            nx, ny = dot(g.normal, v.frame.x), dot(g.normal, v.frame.y)
            side = ("right" if nx > 0 else "left") if abs(nx) >= abs(ny) else ("top" if ny > 0 else "bottom")
            v.group_side[g.face_id] = side
            bw, bh = g.box_size()
            if g.frames or g.datum:
                per_side.setdefault(side, []).append(bh if side in ("top", "bottom") else bw)
            per_side.setdefault(side, []).extend([SF_HEIGHT] * len(g.finish))
        for side, needs in per_side.items():
            # annotations sit on levels beyond the tiers
            step = max(needs) + 2.0
            # one level is reserved; boxes that do not fit side by side stack outward (QA verifies)
            v.group_levels[side] = (step, len(needs))
            v.margins[side] = max(v.margins[side], v.tier_margin[side] + FACE_OFFSET + step)
        # cutting-plane ends beyond everything else on the sides the plane's trace runs to; section label below
        if v.trace:
            sides = ("left", "right") if self._trace_horizontal(v) else ("top", "bottom")
            v.trace_base = {sd: v.margins[sd] for sd in sides}
            for sd in sides:
                v.margins[sd] += SECTION_END
        if v.section:
            v.margins["bottom"] += SECTION_LABEL
        # leader-note column on the right of the right-hand tiers
        if v.notes:
            v.notes_x = u1 + v.margins["right"] + 8.0
            v.margins["right"] = v.margins["right"] + 8.0 + max(n.width() for n in v.notes) + 3.0
            total_h = sum(n.height() + NOTE_GAP * 2 for n in v.notes)
            extra_v = max(0.0, total_h - (w1 - w0)) / 2
            v.margins["top"] = max(v.margins["top"], extra_v)
            v.margins["bottom"] = max(v.margins["bottom"], extra_v)
        if v.pictorial:
            v.margins = {"top": 2.0, "bottom": 2.0, "left": 2.0, "right": 2.0}

    @staticmethod
    def _trace_horizontal(v: _ViewCtx) -> bool:
        n = v.trace[2]
        return abs(dot(n, v.frame.y)) > abs(dot(n, v.frame.x))

    def _section_line(self, v: _ViewCtx, s, c, outline: Rect) -> AnnotationOp:
        """ISO 128-44: thick ends of the cutting plane outside the view's dimensions, arrows in the
        direction of sight (toward the kept half), the section letter at each end."""
        letter, point, n = v.trace
        nx, ny = dot(n, v.frame.x), dot(n, v.frame.y)
        ln = math.hypot(nx, ny) or 1.0
        sight = (-nx / ln, -ny / ln)
        px, py = self._sheet(v, s, c, point)
        b = v.trace_base
        if self._trace_horizontal(v):
            xa, xb = outline.x0 - b["left"] - 2.0, outline.x1 + b["right"] + 2.0
            pts = [(xa - SECTION_STROKE, py), (xa, py), (xb, py), (xb + SECTION_STROKE, py)]
        else:
            ya, yb = outline.y0 - b["bottom"] - 2.0, outline.y1 + b["top"] + 2.0
            pts = [(px, ya - SECTION_STROKE), (px, ya), (px, yb), (px, yb + SECTION_STROKE)]
        return AnnotationOp(id=f"SEC-{letter}", view_id=v.id, kind=AnnotationKind.SECTION_LINE,
                            points=[_r(q) for q in pts], label=letter, direction=_r(sight))

    def _vs(self, v: _ViewCtx, s: float) -> float:
        """Scale factor of a view: the pictorial view may use its own scale."""
        return self.pict_scale[1] if v.pictorial and self.pict_scale else s

    def _extent(self, v: _ViewCtx, s: float) -> tuple[float, float, float, float]:
        """Distances from the view centre to its envelope edges: (left, right, down, up)."""
        vs = self._vs(v, s)
        u0, u1, w0, w1 = (x * vs for x in v.half)
        m = v.margins
        label = PICT_LABEL_SPACE if v.pictorial and self.pict_scale and vs != s else 0.0
        return -u0 + m["left"], u1 + m["right"], -w0 + m["bottom"] + label, w1 + m["top"]

    def _layout(self, s: float, corner_only: bool = False) -> dict[str, tuple[float, float]] | None:
        """The pictorial view (it needs no projection alignment) takes the sheet's top-right corner
        and the orthographic grid is laid out around it, anchored top-left. With ``corner_only``
        False, fallbacks: the pictorial view beside the grid / in any free area, then a free grid cell."""
        for v in self.views:
            self._plan_view(v, s)
        pict = [v for v in self.views if v.pictorial]
        if not pict:
            for pos, _ in self._grid_positions(s, self.views, limit=1):
                return pos
            return None
        ortho = [v for v in self.views if not v.pictorial]
        corner = self._corner_spot(self._extent(pict[0], s)) if len(pict) == 1 else None
        if corner is not None:
            (cx, cy), env = corner
            saved = self.obstacles
            self.obstacles = saved + [Rect(x0=env.x0 - VIEW_GAP, y0=env.y0 - VIEW_GAP, x1=env.x1 + VIEW_GAP,
                                           y1=env.y1 + VIEW_GAP)]
            try:
                for pos, _ in self._grid_positions(s, ortho, limit=12, left_first=True):
                    pos[pict[0].id] = (cx, cy)
                    return pos
            finally:
                self.obstacles = saved
        if corner_only:
            return None
        for pos, envs in self._grid_positions(s, ortho, limit=12, left_first=True):
            placed = list(envs)
            ok = True
            for v in pict:
                spot = (self._top_right_spot(self._extent(v, s), placed)
                        or self._free_spot(self._extent(v, s), placed, top_right=True))
                if spot is None:
                    ok = False
                    break
                pos[v.id], env = spot
                placed.append(env)
            if ok:
                return pos
        for pos, _ in self._grid_positions(s, self.views, limit=1):
            return pos
        return None

    def _corner_spot(self, ext):
        """Envelope in the sheet's top-right corner (below a revision table, if any)."""
        le, ri, do, up = ext
        a = self.area
        cx = a.x1 - ri
        for k in range(int(max(0.0, a.h - up - do) / 2.0) + 1):
            cy = a.y1 - up - k * 2.0
            env = Rect(x0=cx - le, y0=cy - do, x1=cx + ri, y1=cy + up)
            if env.x0 < a.x0 or not env.inside(a):
                return None
            if not any(env.intersects(o) for o in self.obstacles):
                return (cx, cy), env
        return None

    def _top_right_spot(self, ext, placed: list[Rect]):
        """Pictorial view in the free column right of the orthographic views, top-aligned."""
        le, ri, do, up = ext
        a = self.area
        if not placed:
            return None
        x_free = max(p.x1 for p in placed) + VIEW_GAP
        if a.x1 - x_free < le + ri:
            return None
        cx = x_free + (a.x1 - x_free - le - ri) / 2 + le
        blockers = self.obstacles + placed
        for cy in (a.y1 - up - k * 2.0 for k in range(int(max(0.0, a.h - up - do) / 2.0) + 1)):
            env = Rect(x0=cx - le, y0=cy - do, x1=cx + ri, y1=cy + up)
            if env.inside(a) and not any(env.intersects(o) for o in blockers):
                return (cx, cy), env
        return None

    def _free_spot(self, ext, placed: list[Rect], step: float = 4.0, top_right: bool = False):
        """Most clear position for a free-floating view envelope -> ((cx, cy), envelope) or None.
        ``top_right``: the free position closest to the sheet's top-right corner instead."""
        le, ri, do, up = ext
        a = self.area
        best = None
        blockers = self.obstacles + [Rect(x0=p.x0 - VIEW_GAP, y0=p.y0 - VIEW_GAP, x1=p.x1 + VIEW_GAP,
                                          y1=p.y1 + VIEW_GAP) for p in placed]
        nx = int(max(0.0, a.w - le - ri) / step) + 1
        ny = int(max(0.0, a.h - do - up) / step) + 1
        for i in range(nx):
            for j in range(ny):
                cx, cy = a.x0 + le + i * step, a.y1 - up - j * step
                env = Rect(x0=cx - le, y0=cy - do, x1=cx + ri, y1=cy + up)
                if not env.inside(a) or any(env.intersects(o) for o in blockers):
                    continue
                gaps = [env.x0 - a.x0, a.x1 - env.x1, env.y0 - a.y0, a.y1 - env.y1]
                gaps += [max(o.x0 - env.x1, env.x0 - o.x1, o.y0 - env.y1, env.y0 - o.y1) for o in blockers]
                score = (-round(a.x1 - env.x1 + a.y1 - env.y1, 3), 0, 0) if top_right else (
                    round(min(gaps), 3), -j, -i)
                if best is None or score > best[0]:
                    best = (score, (cx, cy), env)
        return (best[1], best[2]) if best else None

    def _grid_positions(self, s: float, views: list[_ViewCtx], limit: int, left_first: bool = False):
        """Valid placements of the view grid, preferred first: -> [(positions, envelopes)]."""
        grid = _FIRST if self.plan.projection_method == ProjectionMethod.FIRST_ANGLE else _THIRD
        ortho = [v for v in views if not v.pictorial]
        pict = [v for v in views if v.pictorial]
        for v in ortho:
            v.cell = grid[v.orientation]
        used = {v.cell for v in ortho}
        rows = sorted({r for r, _ in used})
        cols = sorted({c for _, c in used})
        for v in pict:
            free = [(r, c) for r in rows for c in cols if (r, c) not in used]
            # pictorial view: a free cell in the top row (as in the references), else a new column
            free.sort(key=lambda rc: (rc[0] != rows[0], rc[0], -rc[1]))
            v.cell = free[0] if free else (rows[0], cols[-1] + 1)
            used.add(v.cell)
        rows = sorted({v.cell[0] for v in views})
        cols = sorted({v.cell[1] for v in views})
        ext = {v.id: self._extent(v, s) for v in views}
        left = {c: max(ext[v.id][0] for v in views if v.cell[1] == c) for c in cols}
        right = {c: max(ext[v.id][1] for v in views if v.cell[1] == c) for c in cols}
        down = {r: max(ext[v.id][2] for v in views if v.cell[0] == r) for r in rows}
        up = {r: max(ext[v.id][3] for v in views if v.cell[0] == r) for r in rows}
        total_w = sum(left[c] + right[c] for c in cols) + VIEW_GAP * (len(cols) - 1)
        total_h = sum(up[r] + down[r] for r in rows) + VIEW_GAP * (len(rows) - 1)
        a = self.area
        if total_w > a.w or total_h > a.h:
            return []
        rel_x, x = {}, 0.0
        for c in cols:
            rel_x[c] = x + left[c]
            x += left[c] + right[c] + VIEW_GAP
        rel_y, y = {}, 0.0
        for r in rows:
            rel_y[r] = y - up[r]
            y -= up[r] + down[r] + VIEW_GAP
        inner = Rect(x0=a.x0 - 1e-6, y0=a.y0 - 1e-6, x1=a.x1 + 1e-6, y1=a.y1 + 1e-6)

        def envelopes(ax: float, ay: float) -> list[Rect] | None:
            out = []
            for v in views:
                le, ri, do, upx = ext[v.id]
                cx, cy = ax + rel_x[v.cell[1]], ay + rel_y[v.cell[0]]
                env = Rect(x0=cx - le, y0=cy - do, x1=cx + ri, y1=cy + upx)
                if not env.inside(inner) or any(env.intersects(o) for o in self.obstacles):
                    return None
                out.append(env)
            return out

        def result(ax: float, ay: float, envs):
            return {v.id: (ax + rel_x[v.cell[1]], ay + rel_y[v.cell[0]]) for v in views}, envs

        out = []
        anchors = [  # centred, top-left, top-right, centred above the title block
            (a.x0 + (a.w - total_w) / 2, a.y1 - (a.h - total_h) / 2), (a.x0, a.y1), (a.x1 - total_w, a.y1)]
        if left_first:  # leave the right-hand side free for the pictorial view
            anchors = [(a.x0, a.y1), (a.x0, a.y1 - (a.h - total_h) / 2)]
        above_h = a.y1 - self.obstacles[0].y1
        if total_h <= above_h:
            anchors.append((a.x0 + (a.w - total_w) / 2, a.y1 - (above_h - total_h) / 2))
        for ax, ay in anchors:
            envs = envelopes(ax, ay)
            if envs is not None:
                out.append(result(ax, ay, envs))
                if len(out) >= limit:
                    return out
        # sweep the free area and rank by clearance to the frame and to the title block / notes / revisions
        scored = []
        step = 4.0
        for i in range(int(max(0.0, a.w - total_w) / step) + 1):
            for j in range(int(max(0.0, a.h - total_h) / step) + 1):
                ax, ay = a.x0 + i * step, a.y1 - j * step
                envs = envelopes(ax, ay)
                if envs is None:
                    continue
                box = envs[0]
                for e in envs[1:]:
                    box = box.union(e)
                gaps = [box.x0 - a.x0, a.x1 - box.x1, box.y0 - a.y0, a.y1 - box.y1]
                gaps += [max(o.x0 - box.x1, box.x0 - o.x1, o.y0 - box.y1, box.y0 - o.y1, 0.0)
                         for o in self.obstacles]
                scored.append(((round(min(gaps), 3), -i, -j), ax, ay, envs))
        if left_first:
            scored = [((neg_i, neg_j), ax, ay, envs) for (_, neg_i, neg_j), ax, ay, envs in scored]  # top-left first
        scored.sort(key=lambda t: t[0], reverse=True)
        out += [result(ax, ay, envs) for _, ax, ay, envs in scored[: max(0, limit - len(out))]]
        return out

    # ------------------------------------------------------------------ compile
    def compile(self) -> CompiledDrawing:
        sheet = self.plan.sheet
        self.series = list(scale_series(sheet.scale_system))  # large -> small
        if sheet.scale != "AUTO":  # the user's scale is used as chosen, never changed by repairs
            scales = [sheet.scale]
        else:
            scales = self.series
            if self.opt.max_scale:
                limit = scale_factor(self.opt.max_scale) + 1e-9
                scales = [x for x in scales if scale_factor(x) <= limit]
        found = self._search_variants(scales)
        if found:
            _, _, _, variant, sc, s, pos, pict = min(found, key=lambda t: t[:3])
            self._set_notes(variant)
            self.pict_scale = pict
            self._layout(s)  # restore per-view margins for this scale
            return self._emit(sc, s, pos)
        if sheet.scale != "AUTO" or sheet.pictorial_scale != "AUTO":
            fixed = []
            if sheet.scale != "AUTO":
                fixed.append(f"scale {sheet.scale}")
            if sheet.pictorial_scale != "AUTO":
                fixed.append(f"isometric scale {sheet.pictorial_scale}")
            best = None
            if sheet.scale != "AUTO":
                hits = self._search_variants([x for x in self.series if scale_factor(x) < scale_factor(sheet.scale)])
                best = min(hits, key=lambda t: t[:3])[4] if hits else None
            raise LayoutError(f"the views do not fit on the selected {sheet.size.value} sheet at the chosen "
                              + " and ".join(fixed)
                              + (f" - the largest scale that fits is {best}" if best else "")
                              + " (choose a smaller scale, AUTO or a larger sheet)")
        hint = ""
        if self.sheet_notes and self.plan.general_notes.enabled:
            hint = (f" (with the {len(self.sheet_notes)}-line notes block above the title block - use a larger "
                    "sheet or turn off the default notes)")
        raise LayoutError("the views do not fit on the selected sheet at any drawing scale" + hint)

    def _search_variants(self, scales: list[str]) -> list:
        """-> [(pictorial view not in the corner, scale index, variant index, variant, scale, s, positions,
        pictorial scale)] - sorted by the first three, the corner placement wins over scale and notes."""
        found = []
        for variant in self.notes_variants:
            if not self._set_notes(variant):
                continue
            hit = self._search(scales)
            if hit is not None:
                sc, s, pos, pict, corner = hit
                found.append((not corner, self.series.index(sc) if sc in self.series else 0,
                              self.notes_variants.index(variant), variant, sc, s, pos, pict))
        return found

    def _pict_steps(self, i: int) -> tuple[int, ...]:
        """Scale-step offsets for the undimensioned pictorial view (negative = larger): the smallest
        scale at which it is drawn larger than every orthographic view comes first."""
        pict = [v for v in self.views if v.pictorial]
        if not pict:
            return (0,)
        size = lambda v: max(v.half[1] - v.half[0], v.half[3] - v.half[2])  # noqa: E731
        ortho = max((size(v) for v in self.views if not v.pictorial), default=0.0)
        larger_at_same = min(size(v) for v in pict) > ortho * (1 + 1e-6)
        steps = (0, -1) if larger_at_same else (-1, 0)
        return tuple(k for k in steps if 0 <= i + k < len(self.series))

    def _pict_options(self, sc: str, allowed: tuple[int, ...]) -> list[str]:
        """Pictorial-view scales to try with sheet scale ``sc``."""
        fixed = self.plan.sheet.pictorial_scale
        if fixed != "AUTO":
            return [fixed] if allowed == (-1, 0) else []
        i = self.series.index(sc) if sc in self.series else min(
            range(len(self.series)), key=lambda k: abs(scale_factor(self.series[k]) - scale_factor(sc)))
        steps = self._pict_steps(i) if allowed == (-1, 0) else tuple(
            k for k in allowed if i + k < len(self.series))
        return [self.series[i + k] if self.series[i + k] != sc else sc for k in steps]

    def _search(self, scales: list[str]):
        if not any(v.pictorial for v in self.views):
            self.pict_scale = None
            for sc in scales:
                pos = self._layout(scale_factor(sc))
                if pos is not None:
                    return sc, scale_factor(sc), pos, None, True
            return None
        # the pictorial view's place (top-right corner) comes first, then its size: larger than (or as
        # large as) the orthographic views, else up to two steps smaller (labelled). Only if no
        # scale allows the corner does it move elsewhere.
        for corner_only in (True, False):
            for allowed in ((-1, 0), (1, 2)):
                for sc in scales:
                    s = scale_factor(sc)
                    for p_sc in self._pict_options(sc, allowed):
                        self.pict_scale = (p_sc, scale_factor(p_sc)) if p_sc != sc else None
                        pos = self._layout(s, corner_only=corner_only)
                        if pos is not None:
                            return sc, s, pos, self.pict_scale, corner_only
        return None

    def _sheet(self, v: _ViewCtx, s: float, c: tuple[float, float], p) -> tuple[float, float]:
        a, b = self._uv(v, p)
        return (round(c[0] + a * s, 4), round(c[1] + b * s, 4))

    def _emit(self, sc: str, s: float, pos) -> CompiledDrawing:
        views, dims, anns, pmi = [], [], [], []
        for v in self.views:
            c = pos[v.id]
            vs = self._vs(v, s)
            u0, u1, w0, w1 = (x * vs for x in v.half)
            outline = Rect(x0=c[0] + u0, y0=c[1] + w0, x1=c[0] + u1, y1=c[1] + w1)
            own = v.pictorial and self.pict_scale is not None
            label, label_at = (f"SCALE {self.pict_scale[0]}" if own else None), None
            if v.section:
                label = f"{v.section[0]}-{v.section[0]}"
                label_at = _r(((outline.x0 + outline.x1) / 2, outline.y0 - v.margins["bottom"] + SECTION_LABEL / 2))
            views.append(CompiledView(
                id=v.id, orientation=v.orientation, pictorial=v.pictorial, eye=v.frame.eye, x_axis=v.frame.x,
                y_axis=v.frame.y, scale=self.pict_scale[0] if own else sc, scale_factor=vs, model_center=self.center,
                sheet_center=c, outline=outline, display_style=v.style, label=label, label_at=label_at,
                cut_point=v.section[1] if v.section else None, cut_normal=v.section[2] if v.section else None,
            ))
            if v.trace and not v.pictorial:
                anns.append(self._section_line(v, s, c, outline))
            if v.pictorial:
                continue
            vdims = self._emit_linear(v, s, c, outline) + self._emit_notes(v, s, c, outline)
            dims.extend(vdims)
            taken = [d.text_bbox for d in vdims] + [d.extra_bbox for d in vdims if d.extra_bbox]
            pmi.extend(self._emit_groups(v, s, c, outline, taken))
            if self.plan.annotations.center_marks or self.plan.annotations.centerlines:
                anns.extend(self._emit_annotations(v, s, c))
        return CompiledDrawing(
            source_sha256=self.plan.geometry.source_sha256,
            drawing_kind=self.plan.drawing_kind,
            standard=self.plan.drawing_standard,
            projection_method=self.plan.projection_method,
            sheet_size=self.plan.sheet.size,
            sheet_orientation=self.plan.sheet.orientation,
            sheet_w=self.sheet_w, sheet_h=self.sheet_h,
            frame=self.frame_rect, title_block=self.title_rect, scale=sc,
            views=views, dimensions=dims, annotations=anns, pmi=pmi,
            title_fields=self._title_fields(sc),
            zones=self.zones, sheet_notes=self.sheet_notes, notes_rect=self.notes_rect, notes_split=self.notes_split,
            revision_rows=self.revision_rows, revision_rect=self.revision_rect,
            stamp=Stamp(text=self.opt.stamp, rect=self.stamp_rect) if self.stamp_rect is not None else None,
            notes=list(self.opt.notes)
            + [u.message for u in self.plan.uncertainties if "omitted: redundant" not in u.message],
        )

    # ------------------------------------------------------------------ linear dimensions
    def _emit_linear(self, v: _ViewCtx, s, c, outline: Rect) -> list[DimensionOp]:
        out = []
        for cand, horizontal, p1, p2 in v.dims:
            q1, q2 = self._sheet(v, s, c, p1), self._sheet(v, s, c, p2)
            side = v.side_of[cand.id]
            off = v.tier_off[side][v.tiers[cand.id]]
            sign = {"top": 1, "right": 1, "bottom": -1, "left": -1}[side]
            line_at = {
                "top": outline.y1 + off, "bottom": outline.y0 - off,
                "left": outline.x0 - off, "right": outline.x1 + off,
            }[side]
            tw, th = self._label_width(cand), self._label_height(cand)
            if horizontal:
                mx = (q1[0] + q2[0]) / 2
                bbox = Rect(x0=mx - tw / 2, y0=line_at + 1.0, x1=mx + tw / 2, y1=line_at + 1.0 + th)
            else:
                my = (q1[1] + q2[1]) / 2
                bbox = Rect(x0=line_at - 1.0 - th, y0=my - tw / 2, x1=line_at - 1.0, y1=my + tw / 2)
            op = dict(
                id=cand.id, view_id=v.id, kind=DimensionOpKind.LINEAR, text=cand.text, value=cand.value,
                p1=q1, p2=q2, line_at=round(line_at, 4), horizontal=horizontal, text_bbox=bbox,
                snap={CandidateRole.LOCATION: [True, False], CandidateRole.PITCH: [False, False]}.get(
                    cand.role, [True, True]),
                feature_ids=cand.feature_ids, tolerance=self._tolerance(cand),
                inspection=cand.id in self.m.inspection_dimensions,
                basic=cand.id in self.m.basic_dimensions,
            )
            a = self.dim_attach.get(cand.id)
            if a and not a.empty:
                op.update(self._dim_attachment(a, horizontal, sign, line_at, q1, q2, bbox))
            out.append(DimensionOp(**op))
        return out

    def _dim_attachment(self, a: _Attach, horizontal: bool, sign: int, line_at: float, q1, q2, bbox: Rect) -> dict:
        """Frames beyond the text (outward); datum symbol on the dimension line near p1, box outward."""
        res: dict = {"frames": a.frames}
        extent = None
        if horizontal:
            fx = (bbox.x0 + bbox.x1) / 2 - max(fr.width for fr in a.frames) / 2 if a.frames else 0
            length = abs(q2[0] - q1[0])
            bx = min(q1[0], q2[0]) + max(min(5.0, length / 2), 0.15 * length)
            if a.datum and a.frames:  # keep the datum line clear of the frames
                fx = max(fx, bx + DATUM_BOX / 2 + 2.0)
            top = (bbox.y1 + 1.5 + FRAME_H * len(a.frames)) if sign > 0 else (line_at - 1.0)
            if a.frames:
                res["frames_origin"] = _r((fx, top))
            extent = Rect(x0=fx, y0=top - FRAME_H * len(a.frames), x1=fx + max([f.width for f in a.frames] + [0]),
                          y1=top) if a.frames else None
            if a.datum:
                y_far = (extent.y1 if sign > 0 and extent else bbox.y1) if sign > 0 else (
                    extent.y0 if extent else line_at - 1.0)
                y_box = y_far + sign * DATUM_DROP
                box = Rect(x0=bx - DATUM_BOX / 2, y0=min(y_box, y_box + sign * DATUM_BOX),
                           x1=bx + DATUM_BOX / 2, y1=max(y_box, y_box + sign * DATUM_BOX))
                res.update(datum=a.datum, datum_box=box,
                           datum_line=[_r((bx, line_at)), _r((bx, box.y0 if sign > 0 else box.y1))])
                extent = box if extent is None else extent.union(box)
            if a.finish:
                fw = finish_width(a.finish)
                x0 = (bbox.x0 + bbox.x1) / 2 - fw / 2
                y0 = ((extent.y1 if extent else bbox.y1) + 1.0) if sign > 0 else (
                    (extent.y0 if extent else line_at - 1.0) - SF_HEIGHT)
                box = Rect(x0=x0, y0=y0, x1=x0 + fw, y1=y0 + SF_HEIGHT - 1.0)
                res.update(finish=a.finish, finish_tip=_r((x0 + FINISH_TIP_X, y0)))
                extent = box if extent is None else extent.union(box)
        else:
            # vertical dims: text sits left of the line; frames go outward (right of the line on the
            # right side, left of the text on the left side)
            fx0 = (line_at + 1.0) if sign > 0 else (bbox.x0 - 1.0 - max([f.width for f in a.frames] + [0]))
            my = (bbox.y0 + bbox.y1) / 2
            length = abs(q2[1] - q1[1])
            by = min(q1[1], q2[1]) + max(min(5.0, length / 2), 0.15 * length)
            half = FRAME_H * len(a.frames) / 2
            if a.datum and a.frames and my - half < by + DATUM_BOX / 2 + 2.0:
                my = by + DATUM_BOX / 2 + 2.0 + half  # keep the datum line clear of the frames
            if a.frames:
                res["frames_origin"] = _r((fx0, my + FRAME_H * len(a.frames) / 2))
            extent = Rect(x0=fx0, y0=my - FRAME_H * len(a.frames) / 2,
                          x1=fx0 + max([f.width for f in a.frames] + [0]),
                          y1=my + FRAME_H * len(a.frames) / 2) if a.frames else None
            if a.datum:
                x_far = (extent.x1 if extent else line_at) if sign > 0 else (extent.x0 if extent else bbox.x0)
                x_box = x_far + sign * DATUM_DROP
                box = Rect(x0=min(x_box, x_box + sign * DATUM_BOX), y0=by - DATUM_BOX / 2,
                           x1=max(x_box, x_box + sign * DATUM_BOX), y1=by + DATUM_BOX / 2)
                res.update(datum=a.datum, datum_box=box,
                           datum_line=[_r((line_at, by)), _r((box.x0 if sign > 0 else box.x1, by))])
                extent = box if extent is None else extent.union(box)
            if a.finish:
                fw = finish_width(a.finish)
                x0 = ((extent.x1 if extent else line_at) + 2.0) if sign > 0 else (
                    (extent.x0 if extent else bbox.x0) - 2.0 - fw)
                y0 = (bbox.y0 + bbox.y1) / 2 - SF_HEIGHT / 2
                box = Rect(x0=x0, y0=y0, x1=x0 + fw, y1=y0 + SF_HEIGHT - 1.0)
                res.update(finish=a.finish, finish_tip=_r((x0 + FINISH_TIP_X, y0)))
                extent = box if extent is None else extent.union(box)
        res["extra_bbox"] = extent
        return res

    # ------------------------------------------------------------------ leader notes
    def _note_target(self, v: _ViewCtx, s, c, n: _Note, toward: tuple[float, float]):
        """Arrow tip on the feature, aimed toward the note landing point."""
        f = v.frame
        cand = n.cand
        if cand is None:  # feature / face note
            return self._sheet(v, s, c, n.face_point)
        if cand.kind in (CandidateKind.HOLE_CALLOUT, CandidateKind.PCD, CandidateKind.RADIUS):
            centre3d = cand.center
            if cand.kind == CandidateKind.HOLE_CALLOUT and cand.count > 1:
                # attach an nX callout to the member nearest the note, so the leader stays short
                members = [self.features[i].axis.origin for i in cand.feature_ids
                           if i in self.features and self.features[i].type == FeatureType.HOLE]
                if members:
                    centre3d = min(members, key=lambda m: (
                        math.dist(self._sheet(v, s, c, m), toward), tuple(round(x, 6) for x in m)))
            ctr = self._sheet(v, s, c, centre3d)
            r = cand.radius * s
            if cand.kind == CandidateKind.RADIUS and cand.anchor is not None:
                a = self._sheet(v, s, c, cand.anchor)
                d = (a[0] - ctr[0], a[1] - ctr[1])
            else:
                d = (toward[0] - ctr[0], toward[1] - ctr[1])
            nn = math.hypot(*d) or 1.0
            return (round(ctr[0] + d[0] / nn * r, 4), round(ctr[1] + d[1] / nn * r, 4))
        if cand.kind == CandidateKind.CHAMFER:
            if cand.view_rule == ViewRule.ACROSS_AXIS:
                perp = f.x if abs(dot(cand.axis, f.x)) < 1e-6 else f.y
                return self._sheet(v, s, c, _add(cand.center, _mul(perp, cand.radius)))
            return self._sheet(v, s, c, cand.anchor)
        return self._sheet(v, s, c, cand.center or cand.anchor)

    def _emit_notes(self, v: _ViewCtx, s, c, outline: Rect) -> list[DimensionOp]:
        if not v.notes:
            return []
        x = c[0] + v.notes_x
        prov = []
        for n in v.notes:
            ref = n.face_point if n.cand is None else (n.cand.center or n.cand.anchor)
            tip = self._note_target(v, s, c, n, (x, self._sheet(v, s, c, ref)[1]))
            prov.append((tip[1], n))
        prov.sort(key=lambda t: (-t[0], t[1].id))
        out, y_prev = [], None
        for y_tip, n in prov:
            y = y_tip
            if y_prev is not None:
                # a stacked tolerance raises the label above its text line
                raised = (self._label_height(n.cand) - TEXT_H) if n.cand is not None else 0.0
                y = min(y, y_prev - NOTE_GAP * 2 - raised)
            land = (round(x, 4), round(y, 4))
            tip = self._note_target(v, s, c, n, land)
            th, tw = text_height(n.text), text_width(n.text)
            if n.cand is not None:
                tw = max(tw, self._label_width(n.cand))
            top = y + TEXT_H / 2 + ((self._label_height(n.cand) - TEXT_H) if n.cand is not None else 0.0)
            bbox = Rect(x0=x + 1.0, y0=y - th + TEXT_H / 2, x1=x + 1.0 + tw, y1=top)
            op = dict(
                id=n.id, view_id=v.id, kind=DimensionOpKind.LEADER_NOTE, text=n.text, value=n.value,
                leader=[tip, land], text_at=(round(x + 1.0, 4), round(y, 4)), text_bbox=bbox,
                feature_ids=n.feature_ids,
                tolerance=self._tolerance(n.cand) if n.cand else None,
                inspection=n.id in self.m.inspection_dimensions,
                basic=n.id in self.m.basic_dimensions,
            )
            bottom = bbox.y0
            extent = None
            if n.attach.frames:
                top = bottom - 1.0
                op["frames"] = n.attach.frames
                op["frames_origin"] = _r((x + 1.0, top))
                extent = Rect(x0=x + 1.0, y0=top - FRAME_H * len(n.attach.frames),
                              x1=x + 1.0 + max(fr.width for fr in n.attach.frames), y1=top)
                bottom = extent.y0
            if n.attach.datum:
                box = Rect(x0=x - DATUM_BOX / 2, y0=bottom - DATUM_DROP - DATUM_BOX, x1=x + DATUM_BOX / 2,
                           y1=bottom - DATUM_DROP)
                op.update(datum=n.attach.datum, datum_box=box, datum_line=[land, _r((x, box.y1))])
                extent = box if extent is None else extent.union(box)
                bottom = box.y0
            if n.attach.finish:
                y0 = bottom - SF_HEIGHT
                box = Rect(x0=x + 1.0, y0=y0, x1=x + 1.0 + finish_width(n.attach.finish), y1=y0 + SF_HEIGHT - 1.0)
                op.update(finish=n.attach.finish, finish_tip=_r((x + 1.0 + FINISH_TIP_X, y0)))
                extent = box if extent is None else extent.union(box)
                bottom = y0
            op["extra_bbox"] = extent
            y_prev = bottom
            out.append(DimensionOp(**op))
        return out

    # ------------------------------------------------------------------ face annotation groups
    def _emit_groups(self, v: _ViewCtx, s, c, outline: Rect, taken: list[Rect]) -> list[PmiOp]:
        """Face annotations: frame/datum groups and surface texture symbols, each on a leader
        from the edge-on face to a box outside the dimension tiers. The leader foot is moved
        along the face so that no leader or box crosses dimension text, frames or other groups."""
        out: list[PmiOp] = []
        taken = list(taken)

        def free(r: Rect) -> bool:
            return r.inside(self.area) and not any(r.intersects(t, 0.8) for t in taken)

        for g in v.groups:
            side = v.group_side[g.face_id]
            d = {"top": (0, 1), "bottom": (0, -1), "right": (1, 0), "left": (-1, 0)}[side]
            vertical_side = side in ("top", "bottom")
            base = self._sheet(v, s, c, g.point)
            pts = [self._sheet(v, s, c, q) for e in self.ir.edges if e.id in set(self.faces[g.face_id].edge_ids)
                   for q in (e.start, e.end)] or [base]
            k_al = 0 if vertical_side else 1
            lo, hi = min(q[k_al] for q in pts), max(q[k_al] for q in pts)
            edge = {"top": outline.y1, "bottom": outline.y0, "right": outline.x1, "left": outline.x0}[side]
            near0 = edge + (d[0] + d[1]) * (v.tier_margin.get(side, 0.0) + FACE_OFFSET)

            def geometry(a: float, t: float, al0: float, al1: float, near: float, bw: float, bh: float):
                """Box anchored at ``a`` (along the face direction), leader foot at ``t`` on the face."""
                tip = (t, base[1]) if vertical_side else (base[0], t)
                if vertical_side:
                    y0 = near if side == "top" else near - bh
                    box = Rect(x0=a + al0, y0=y0, x1=a + al1, y1=y0 + bh)
                    land = (a, box.y0 if side == "top" else box.y1)
                else:
                    x0 = near if side == "right" else near - bw
                    box = Rect(x0=x0, y0=a + al0, x1=x0 + bw, y1=a + al1)
                    land = (box.x0 if side == "right" else box.x1, a)
                return tip, land, box

            def place(bw: float, bh: float, spans: list[tuple[float, float]], what: str):
                """-> (tip, land, box). Straight leaders first; then boxes shifted sideways with an
                angled leader from the face; then further levels outward (QA checks the envelope)."""
                length = hi - lo
                on_face = [lo + f * length for f in TIP_FRACTIONS]
                sideways = [x for k in range(1, 17) for x in (lo - 6.0 * k, hi + 6.0 * k)]
                step, _n = v.group_levels.get(side, (0.0, 1))
                for lv in range(5):
                    near = near0 + (d[0] + d[1]) * lv * step
                    for a in on_face + sideways:
                        t = min(max(a, lo + 0.1 * length), hi - 0.1 * length)
                        for al0, al1 in spans:
                            tip, land, box = geometry(a, t, al0, al1, near, bw, bh)
                            if free(box) and not any(_segment_hits(tip, land, r, skip=1.0) for r in taken):
                                taken.append(box)
                                taken.extend(_segment_boxes(tip, land))
                                return _r(tip), _r(land), box
                self.opt.notes.append(f"CROWDED: {what} on {g.face_id} overlaps other annotations in {v.id}")
                tip, land, box = geometry(on_face[0], on_face[0], *spans[0], near0, bw, bh)
                taken.append(box)
                return _r(tip), _r(land), box

            if g.frames or g.datum:
                bw, bh = g.box_size()
                span = bw if vertical_side else bh
                tip, land, box = place(bw, bh, [(-span / 2, span / 2), (-2.0, span - 2.0), (2.0 - span, 2.0)], "GD&T")
                frames_origin = _r((box.x0, box.y1)) if g.frames else None
                datum_box = None
                if g.datum:
                    # with frames the datum symbol hangs under the frame (it identifies the same face)
                    datum_box = Rect(x0=box.x0, y0=box.y0, x1=box.x0 + DATUM_BOX, y1=box.y0 + DATUM_BOX) \
                        if g.frames else box
                out.append(PmiOp(
                    id=f"PMI-{g.face_id}-{v.id}", view_id=v.id, kind=PmiKind.FRAME_GROUP, tip=tip, direction=d,
                    leader=[tip, land], arrow=bool(g.frames), frames=g.frames, frames_origin=frames_origin,
                    datum=g.datum, datum_box=datum_box, bbox=box, target=g.face_id,
                ))
            for k, ra in enumerate(g.finish):
                # ISO 1302 symbol on a leader; its along-face extent: short leg (-3.5) .. Ra text
                text = f"Ra {fmt(ra, 2, False)}"
                ra_w = 7.5 + len(text) * CHAR_W * TOL_H
                bw, bh = (ra_w + 3.5, SF_HEIGHT) if vertical_side else (SF_HEIGHT, ra_w + 3.5)
                tip, land, box = place(bw, bh, [(-3.5, ra_w)], "surface finish")
                out.append(PmiOp(
                    id=f"SF-{g.face_id}-{k}-{v.id}", view_id=v.id, kind=PmiKind.SURFACE_FINISH, tip=land,
                    direction=d, leader=[tip, land], arrow=True, text=text, bbox=box, target=g.face_id,
                ))
        return out

    # ------------------------------------------------------------------ center marks / lines
    def _emit_annotations(self, v: _ViewCtx, s, c) -> list[AnnotationOp]:
        f = v.frame
        out = []
        cyl = [x for x in self.ir.features if x.type in (FeatureType.HOLE, FeatureType.BOSS)]
        seen_marks: set[tuple] = set()
        for feat in sorted(cyl, key=lambda x: x.id):
            ax, org = feat.axis.direction, feat.axis.origin
            r = feat.diameter / 2 * s
            length = feat.depth if feat.type == FeatureType.HOLE else feat.height
            if abs(dot(ax, f.eye)) > 1 - 1e-6:
                if not self.plan.annotations.center_marks:
                    continue
                ctr = self._sheet(v, s, c, org)
                key = (round(ctr[0], 2), round(ctr[1], 2))
                if key in seen_marks:
                    continue
                seen_marks.add(key)
                e = r + CENTER_EXT
                out.append(AnnotationOp(
                    id=f"CM-{feat.id}-{v.id}", view_id=v.id, kind=AnnotationKind.CENTER_MARK, center=ctr, radius=e,
                    points=[(ctr[0] - e, ctr[1]), (ctr[0] + e, ctr[1]), (ctr[0], ctr[1] - e), (ctr[0], ctr[1] + e)],
                    feature_ids=[feat.id],
                ))
            elif abs(dot(ax, f.eye)) < 1e-6 and self.plan.annotations.centerlines:
                a = self._sheet(v, s, c, org)
                b = self._sheet(v, s, c, _add(org, _mul(ax, length)))
                d = (b[0] - a[0], b[1] - a[1])
                n = math.hypot(*d) or 1.0
                ext = (d[0] / n * CENTER_EXT, d[1] / n * CENTER_EXT)
                out.append(AnnotationOp(
                    id=f"CL-{feat.id}-{v.id}", view_id=v.id, kind=AnnotationKind.CENTERLINE,
                    points=[(round(a[0] - ext[0], 4), round(a[1] - ext[1], 4)),
                            (round(b[0] + ext[0], 4), round(b[1] + ext[1], 4))],
                    feature_ids=[feat.id],
                ))
        for p in [x for x in self.ir.features if x.type == FeatureType.PATTERN and x.pattern_type == "CIRCULAR"]:
            if abs(dot(p.axis_direction, f.eye)) > 1 - 1e-6 and self.plan.annotations.center_marks:
                out.append(AnnotationOp(
                    id=f"PC-{p.id}-{v.id}", view_id=v.id, kind=AnnotationKind.PITCH_CIRCLE,
                    center=self._sheet(v, s, c, p.center), radius=p.pitch_circle_diameter / 2 * s,
                    feature_ids=[p.id],
                ))
        return out

    # ------------------------------------------------------------------ title block
    def _title_fields(self, sc: str) -> list[TitleBlockField]:
        """Keys used by the executor's title-block template. Unsupplied engineering data is
        printed as UNSPECIFIED; unsupplied identification / sign-off fields stay blank."""
        p = self.plan
        tb = p.title_block
        info = p.engineering_information

        def eng(name: str) -> str:
            fld = getattr(info, name)
            return fld.value if fld.status == "SPECIFIED" else "UNSPECIFIED"

        general = eng("general_tolerance")
        finish_parts = [info.coating.value] if info.coating.status == "SPECIFIED" else []
        if info.heat_treatment.status == "SPECIFIED":
            finish_parts.append(info.heat_treatment.value)
        fields = {
            "TITLE": tb.title or "",
            "DWG_NO": tb.drawing_number or tb.part_number or "",
            "PART_NO": tb.part_number or "",
            "REVISION": tb.revision or "",
            "ORGANIZATION": tb.organization or "",
            "MATERIAL": eng("material"),
            "WEIGHT": tb.weight or "",
            "QTY": tb.quantity or "",
            "SCALE": sc,
            "SHEET_SIZE": p.sheet.size.value,
            "SHEET": "1 OF 1",
            "SURFACE_FINISH": eng("surface_finish"),
            "LINEAR_TOL": eng("linear_tolerance") if info.linear_tolerance.status == "SPECIFIED" else general,
            # a general tolerance class (e.g. ISO 2768-m) covers angles too
            "ANGULAR_TOL": eng("angular_tolerance") if info.angular_tolerance.status == "SPECIFIED" else general,
            "GENERAL_TOL": general,
            "FINISH": ", ".join(finish_parts) if finish_parts else "UNSPECIFIED",
            "EDGES": "DEBURR AND\nBREAK SHARP\nEDGES" if self.m.deburr_break_sharp_edges else "",
            "PROJECTION": p.projection_method.value.replace("_", " "),
            "TYPE": f"{p.drawing_kind.value} DRAWING",
            "STANDARD": p.drawing_standard.value,
            "DATE": (self.opt.generated_on or date.today()).isoformat(),
        }
        for role in ("drawn", "checked", "approved", "mfg", "qa"):
            fields[f"{role.upper()}_NAME"] = getattr(tb, f"{role}_by") or ""
            fields[f"{role.upper()}_DATE"] = getattr(tb, f"{role}_date") or ""
        return [TitleBlockField(label=k, value=v) for k, v in fields.items()]


def compile_drawing(plan: DrawingPlan, candidates: list[DimensionCandidate], ir: GeometryIR,
                    options: CompileOptions | None = None) -> CompiledDrawing:
    return Compiler(plan, candidates, ir, options).compile()


__all__ = ["compile_drawing", "CompileOptions", "LayoutError", "scale_factor", "fmt", "SheetOrientation"]
