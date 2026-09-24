"""DrawingPlan + candidates + GeometryIR -> CompiledDrawing (deterministic sheet layout).

Layout model
------------
* Sheet frame per ISO 5457 (20 mm filing margin left, 10 mm elsewhere); a title-block strip
  (40 mm) is reserved along the bottom of the frame.
* Orthographic views sit on a grid relative to FRONT according to the projection method
  (first angle: TOP below, RIGHT left, LEFT right, BOTTOM above; third angle mirrored).
  Views in a column share the model x-projection, views in a row share the y-projection.
* Each view's *envelope* = projected part outline + dimension tiers on each side + a
  leader-note column on the right. Column widths / row heights come from the envelopes.
* Scale: the largest ISO 5455 scale whose layout fits (optionally capped by QA repair).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from drawing_schema import (
    ISO_5455_SCALES,
    PICTORIAL,
    DrawingPlan,
    ProjectionMethod,
    SheetOrientation,
    ViewOrientation,
    DisplayStyle,
)
from drawing_schema.candidates import CandidateKind, CandidateRole, DimensionCandidate, ViewRule
from drawing_schema.compiled import (
    AnnotationKind,
    AnnotationOp,
    CompiledDrawing,
    CompiledView,
    DimensionOp,
    DimensionOpKind,
    Rect,
    TitleBlockField,
)
from drawing_schema.frames import Frame, dot, view_frame
from geometry_schema import FeatureType, GeometryIR

TEXT_H = 3.5  # mm, ISO 3098 on A3
CHAR_W = 0.62  # width factor per character (approximation used for layout/QA boxes)
FIRST_TIER = 10.0
TIER_GAP = 8.0
VIEW_GAP = 12.0
NOTE_GAP = 2.0
TITLE_H = 40.0
CENTER_EXT = 3.0


class LayoutError(Exception):
    pass


@dataclass
class CompileOptions:
    max_scale: str | None = None  # QA repair: never exceed this scale
    tier_gap: float = TIER_GAP
    generated_on: date | None = None
    notes: list[str] = field(default_factory=list)


def scale_factor(s: str) -> float:
    a, b = s.split(":")
    return float(a) / float(b)


def text_width(text: str, h: float = TEXT_H) -> float:
    return max(len(line) for line in text.split("\n")) * CHAR_W * h


def text_height(text: str, h: float = TEXT_H) -> float:
    n = text.count("\n") + 1
    return n * h + (n - 1) * h * 0.6


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


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
class _ViewCtx:
    id: str
    orientation: ViewOrientation
    frame: Frame
    pictorial: bool
    style: DisplayStyle
    half: tuple[float, float, float, float] = (0, 0, 0, 0)  # model-space extents about center (u0,u1,v0,v1)
    dims: list = field(default_factory=list)  # (candidate, horizontal, side)
    notes: list = field(default_factory=list)  # leader candidates
    margins: dict = field(default_factory=dict)
    tiers: dict = field(default_factory=dict)  # candidate id -> tier index
    cell: tuple[int, int] = (0, 0)


class Compiler:
    def __init__(self, plan: DrawingPlan, candidates: list[DimensionCandidate], ir: GeometryIR,
                 options: CompileOptions | None = None) -> None:
        self.plan, self.ir = plan, ir
        self.opt = options or CompileOptions()
        self.cands = {c.id: c for c in candidates}
        self.features = {f.id: f for f in ir.features}
        bb = ir.bounding_box
        self.center = tuple((bb.min[i] + bb.max[i]) / 2 for i in range(3))
        self.corners = [
            (x, y, z) for x in (bb.min[0], bb.max[0]) for y in (bb.min[1], bb.max[1]) for z in (bb.min[2], bb.max[2])
        ]
        w, h = plan.sheet.dimensions_mm()
        self.sheet_w, self.sheet_h = w, h
        self.frame_rect = Rect(x0=20.0, y0=10.0, x1=w - 10.0, y1=h - 10.0)
        tb_w = min(180.0, self.frame_rect.w)
        self.title_rect = Rect(x0=self.frame_rect.x1 - tb_w, y0=self.frame_rect.y0,
                               x1=self.frame_rect.x1, y1=self.frame_rect.y0 + TITLE_H)
        self.area = Rect(x0=self.frame_rect.x0 + 5, y0=self.title_rect.y1 + 5,
                         x1=self.frame_rect.x1 - 5, y1=self.frame_rect.y1 - 5)
        self.views = self._views()

    # ------------------------------------------------------------------ views & assignment
    def _views(self) -> list[_ViewCtx]:
        p = self.plan
        out: list[_ViewCtx] = []
        pv = p.primary_view
        out.append(_ViewCtx(pv.id, pv.orientation, view_frame(pv.orientation, p.view_frame),
                            pv.orientation in PICTORIAL,
                            DisplayStyle.HIDDEN_LINES_REMOVED if pv.orientation in PICTORIAL else pv.display_style))
        for o in p.projected_views:
            out.append(_ViewCtx(f"V-{o.value}", o, view_frame(o, p.view_frame), False, p.orthographic_display_style))
        for v in out:
            us = [dot(_sub(c, self.center), v.frame.x) for c in self.corners]
            vs = [dot(_sub(c, self.center), v.frame.y) for c in self.corners]
            v.half = (min(us), max(us), min(vs), max(vs))
        by_id = {v.id: v for v in out}
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
                v.notes.append(c)
        return out

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
            sides[side].append((c, span))
        v.tiers, v.margins = {}, {}
        side_of: dict[str, str] = {}
        for side, items in sides.items():
            tiers: list[list[tuple[float, float]]] = []
            for c, span in sorted(items, key=lambda it: (it[1][1] - it[1][0], it[0].priority, it[0].id)):
                tw = text_width(c.text) + 2
                lo, hi = span
                mid = (lo + hi) / 2
                occ = (min(lo, mid - tw / 2) - 1, max(hi, mid + tw / 2) + 1)
                for k, tier in enumerate(tiers):
                    if all(occ[1] <= a or occ[0] >= b for a, b in tier):
                        tier.append(occ)
                        v.tiers[c.id] = k
                        break
                else:
                    tiers.append([occ])
                    v.tiers[c.id] = len(tiers) - 1
                side_of[c.id] = side
            n = len(tiers)
            v.margins[side] = 0.0 if n == 0 else FIRST_TIER + (n - 1) * self.opt.tier_gap + TEXT_H + 2
        v.side_of = side_of
        # leader-note column on the right of the right-hand tiers
        if v.notes:
            widths = [text_width(n.text) for n in v.notes]
            v.notes_x = u1 + v.margins["right"] + 8.0
            v.margins["right"] = v.margins["right"] + 8.0 + max(widths) + 3.0
            total_h = sum(text_height(n.text) + NOTE_GAP * 2 for n in v.notes)
            extra = max(0.0, total_h - (w1 - w0)) / 2
            v.margins["top"] = max(v.margins["top"], extra)
            v.margins["bottom"] = max(v.margins["bottom"], extra)
        if v.pictorial:
            v.margins = {"top": 2.0, "bottom": 2.0, "left": 2.0, "right": 2.0}

    def _extent(self, v: _ViewCtx, s: float) -> tuple[float, float, float, float]:
        """Distances from the view centre to its envelope edges: (left, right, down, up)."""
        u0, u1, w0, w1 = (x * s for x in v.half)
        m = v.margins
        return -u0 + m["left"], u1 + m["right"], -w0 + m["bottom"], w1 + m["top"]

    def _layout(self, s: float) -> dict[str, tuple[float, float]] | None:
        grid = _FIRST if self.plan.projection_method == ProjectionMethod.FIRST_ANGLE else _THIRD
        ortho = [v for v in self.views if not v.pictorial]
        pict = [v for v in self.views if v.pictorial]
        for v in self.views:
            self._plan_view(v, s)
        for v in ortho:
            v.cell = grid[v.orientation]
        used = {v.cell for v in ortho}
        rows = sorted({r for r, _ in used})
        cols = sorted({c for _, c in used})
        for v in pict:
            free = [(r, c) for r in rows for c in cols if (r, c) not in used]
            # prefer a free cell in the top row, else bottom row, else a new column on the right
            free.sort(key=lambda rc: (rc[0] != rows[0], rc[0], -rc[1]))
            v.cell = free[0] if free else (rows[0], cols[-1] + 1)
            used.add(v.cell)
        rows = sorted({v.cell[0] for v in self.views})
        cols = sorted({v.cell[1] for v in self.views})
        ext = {v.id: self._extent(v, s) for v in self.views}
        left = {c: max(ext[v.id][0] for v in self.views if v.cell[1] == c) for c in cols}
        right = {c: max(ext[v.id][1] for v in self.views if v.cell[1] == c) for c in cols}
        down = {r: max(ext[v.id][2] for v in self.views if v.cell[0] == r) for r in rows}
        up = {r: max(ext[v.id][3] for v in self.views if v.cell[0] == r) for r in rows}
        total_w = sum(left[c] + right[c] for c in cols) + VIEW_GAP * (len(cols) - 1)
        total_h = sum(up[r] + down[r] for r in rows) + VIEW_GAP * (len(rows) - 1)
        if total_w > self.area.w or total_h > self.area.h:
            return None
        x = self.area.x0 + (self.area.w - total_w) / 2
        col_x = {}
        for c in cols:
            col_x[c] = x + left[c]
            x += left[c] + right[c] + VIEW_GAP
        y = self.area.y1 - (self.area.h - total_h) / 2
        row_y = {}
        for r in rows:
            row_y[r] = y - up[r]
            y -= up[r] + down[r] + VIEW_GAP
        return {v.id: (col_x[v.cell[1]], row_y[v.cell[0]]) for v in self.views}

    # ------------------------------------------------------------------ compile
    def compile(self) -> CompiledDrawing:
        scales = list(ISO_5455_SCALES)  # large -> small
        if self.opt.max_scale:
            scales = scales[scales.index(self.opt.max_scale):]
        for sc in scales:
            s = scale_factor(sc)
            pos = self._layout(s)
            if pos is not None:
                return self._emit(sc, s, pos)
        raise LayoutError("the views do not fit on the selected sheet at any ISO 5455 scale")

    def _sheet(self, v: _ViewCtx, s: float, c: tuple[float, float], p) -> tuple[float, float]:
        a, b = self._uv(v, p)
        return (round(c[0] + a * s, 4), round(c[1] + b * s, 4))

    def _emit(self, sc: str, s: float, pos) -> CompiledDrawing:
        views, dims, anns = [], [], []
        for v in self.views:
            c = pos[v.id]
            u0, u1, w0, w1 = (x * s for x in v.half)
            outline = Rect(x0=c[0] + u0, y0=c[1] + w0, x1=c[0] + u1, y1=c[1] + w1)
            views.append(CompiledView(
                id=v.id, orientation=v.orientation, pictorial=v.pictorial, eye=v.frame.eye, x_axis=v.frame.x,
                y_axis=v.frame.y, scale=sc, scale_factor=s, model_center=self.center, sheet_center=c,
                outline=outline, display_style=v.style,
                label=v.orientation.value if v.pictorial else None,
            ))
            if v.pictorial:
                continue
            dims.extend(self._emit_linear(v, s, c, outline))
            dims.extend(self._emit_notes(v, s, c, outline))
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
            views=views, dimensions=dims, annotations=anns,
            title_fields=self._title_fields(sc),
            notes=list(self.opt.notes)
            + [u.message for u in self.plan.uncertainties if "omitted: redundant" not in u.message],
        )

    def _emit_linear(self, v: _ViewCtx, s, c, outline: Rect) -> list[DimensionOp]:
        out = []
        for cand, horizontal, p1, p2 in v.dims:
            q1, q2 = self._sheet(v, s, c, p1), self._sheet(v, s, c, p2)
            side = v.side_of[cand.id]
            off = FIRST_TIER + v.tiers[cand.id] * self.opt.tier_gap
            line_at = {
                "top": outline.y1 + off, "bottom": outline.y0 - off,
                "left": outline.x0 - off, "right": outline.x1 + off,
            }[side]
            tw, th = text_width(cand.text), TEXT_H
            if horizontal:
                mx = (q1[0] + q2[0]) / 2
                bbox = Rect(x0=mx - tw / 2, y0=line_at + 1.0, x1=mx + tw / 2, y1=line_at + 1.0 + th)
            else:
                my = (q1[1] + q2[1]) / 2
                bbox = Rect(x0=line_at - 1.0 - th, y0=my - tw / 2, x1=line_at - 1.0, y1=my + tw / 2)
            out.append(DimensionOp(
                id=cand.id, view_id=v.id, kind=DimensionOpKind.LINEAR, text=cand.text, value=cand.value,
                p1=q1, p2=q2, line_at=round(line_at, 4), horizontal=horizontal, text_bbox=bbox,
                snap={CandidateRole.LOCATION: [True, False], CandidateRole.PITCH: [False, False]}.get(
                    cand.role, [True, True]),
                feature_ids=cand.feature_ids,
            ))
        return out

    def _note_target(self, v: _ViewCtx, s, c, cand: DimensionCandidate, toward: tuple[float, float]):
        """Arrow tip on the feature, aimed toward the note landing point."""
        f = v.frame
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
            n = math.hypot(*d) or 1.0
            return (round(ctr[0] + d[0] / n * r, 4), round(ctr[1] + d[1] / n * r, 4))
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
        # provisional tips (aimed right) give the vertical order of the notes
        prov = []
        for cand in v.notes:
            tip = self._note_target(v, s, c, cand, (x, self._sheet(v, s, c, cand.center or cand.anchor)[1]))
            prov.append((tip[1], cand))
        prov.sort(key=lambda t: (-t[0], t[1].id))
        out, y_prev = [], None
        for y_tip, cand in prov:
            th = text_height(cand.text)
            y = y_tip
            if y_prev is not None:
                y = min(y, y_prev - th - NOTE_GAP * 2)
            y_prev = y
            land = (round(x, 4), round(y, 4))
            tip = self._note_target(v, s, c, cand, land)
            tw = text_width(cand.text)
            bbox = Rect(x0=x + 1.0, y0=y - th + TEXT_H / 2, x1=x + 1.0 + tw, y1=y + TEXT_H / 2)
            out.append(DimensionOp(
                id=cand.id, view_id=v.id, kind=DimensionOpKind.LEADER_NOTE, text=cand.text, value=cand.value,
                leader=[tip, land], text_at=(round(x + 1.0, 4), round(y, 4)), text_bbox=bbox,
                feature_ids=cand.feature_ids,
            ))
        return out

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

    def _title_fields(self, sc: str) -> list[TitleBlockField]:
        p = self.plan
        tb = p.title_block
        info = p.engineering_information

        def eng(name: str) -> str:
            f = getattr(info, name)
            return f"{f.value} ({f.source.value})" if f.status == "SPECIFIED" else "UNSPECIFIED"

        return [
            TitleBlockField(label="TITLE", value=tb.title or "UNTITLED"),
            TitleBlockField(label="PART NO.", value=tb.part_number or "—"),
            TitleBlockField(label="REV", value=tb.revision or "—"),
            TitleBlockField(label="DRAWN BY", value=tb.drawn_by or "—"),
            TitleBlockField(label="ORGANIZATION", value=tb.organization or "—"),
            TitleBlockField(label="DATE", value=(self.opt.generated_on or date.today()).isoformat()),
            TitleBlockField(label="SCALE", value=sc),
            TitleBlockField(label="SHEET", value=f"{p.sheet.size.value} {p.sheet.orientation.value}"),
            TitleBlockField(label="UNITS", value="mm"),
            TitleBlockField(label="STANDARD", value=p.drawing_standard.value),
            TitleBlockField(label="PROJECTION", value=p.projection_method.value.replace("_", " ")),
            TitleBlockField(label="TYPE", value=f"{p.drawing_kind.value} DRAWING"),
            TitleBlockField(label="MATERIAL", value=eng("material")),
            TitleBlockField(label="GENERAL TOL.", value=eng("general_tolerance")),
            TitleBlockField(label="SURFACE FINISH", value=eng("surface_finish")),
            TitleBlockField(label="SOURCE SHA-256", value=p.geometry.source_sha256[:16]),
        ]


def compile_drawing(plan: DrawingPlan, candidates: list[DimensionCandidate], ir: GeometryIR,
                    options: CompileOptions | None = None) -> CompiledDrawing:
    return Compiler(plan, candidates, ir, options).compile()


__all__ = ["compile_drawing", "CompileOptions", "LayoutError", "scale_factor", "SheetOrientation"]
