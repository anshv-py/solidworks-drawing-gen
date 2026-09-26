"""Sheet-space geometry: transform HLR lines onto the sheet and snap extension lines."""

from __future__ import annotations

from drawing_schema.compiled import CompiledView, DimensionOp, Rect

from drawing_executor.hlr import Polyline, ViewLines


def to_sheet(lines: list[Polyline], view: CompiledView) -> list[Polyline]:
    s, (cx, cy) = view.scale_factor, view.sheet_center
    return [[(cx + x * s, cy + y * s) for x, y in pl] for pl in lines]


def bbox(polys: list[Polyline]) -> Rect | None:
    xs = [p[0] for pl in polys for p in pl]
    ys = [p[1] for pl in polys for p in pl]
    if not xs:
        return None
    return Rect(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys))


def _hits(polys: list[Polyline], horizontal_dim: bool, coord: float, tol: float = 0.05) -> list[float]:
    """Positions where geometry crosses the extension line (x=coord for horizontal dims, y=coord otherwise)."""
    out = []
    for pl in polys:
        for (x1, y1), (x2, y2) in zip(pl, pl[1:]):
            a1, a2, b1, b2 = (x1, x2, y1, y2) if horizontal_dim else (y1, y2, x1, x2)
            lo, hi = min(a1, a2), max(a1, a2)
            if coord < lo - tol or coord > hi + tol:
                continue
            if abs(a2 - a1) < 1e-9:
                out.extend((b1, b2))
            else:
                t = (coord - a1) / (a2 - a1)
                out.append(b1 + t * (b2 - b1))
    return out


def snap_extension(p: tuple[float, float], d: DimensionOp, polys: list[Polyline]) -> tuple[float, float]:
    """Start the extension line at the geometry nearest to the dimension line (as drafted by hand)."""
    if d.horizontal:
        hits = [y for y in _hits(polys, True, p[0]) if min(p[1], d.line_at) - 1e-6 <= y <= max(p[1], d.line_at) + 1e-6]
        return (p[0], min(hits, key=lambda y: abs(y - d.line_at))) if hits else p
    hits = [x for x in _hits(polys, False, p[1]) if min(p[0], d.line_at) - 1e-6 <= x <= max(p[0], d.line_at) + 1e-6]
    return (min(hits, key=lambda x: abs(x - d.line_at)), p[1]) if hits else p


def all_lines(v: ViewLines) -> list[Polyline]:
    return v.visible + v.hidden


def clip_to_circle(lines: list[Polyline], r: float) -> list[Polyline]:
    """Parts of the polylines inside the circle of radius ``r`` about the origin (detail views)."""
    import math

    out: list[Polyline] = []
    for pl in lines:
        cur: Polyline = []
        for a, b in zip(pl, pl[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            aa = dx * dx + dy * dy
            ins_a = a[0] ** 2 + a[1] ** 2 <= r * r
            if aa < 1e-18:
                continue
            bb = 2 * (a[0] * dx + a[1] * dy)
            cc = a[0] ** 2 + a[1] ** 2 - r * r
            disc = bb * bb - 4 * aa * cc
            if disc < 0:
                if cur:
                    out.append(cur)
                    cur = []
                continue
            sq = math.sqrt(disc)
            t0, t1 = max(0.0, (-bb - sq) / (2 * aa)), min(1.0, (-bb + sq) / (2 * aa))
            if t0 >= t1:
                if cur:
                    out.append(cur)
                    cur = []
                continue
            p0 = (a[0] + dx * t0, a[1] + dy * t0)
            p1 = (a[0] + dx * t1, a[1] + dy * t1)
            if not cur or not ins_a or t0 > 0:
                if cur:
                    out.append(cur)
                cur = [p0]
            cur.append(p1)
            if t1 < 1.0:
                out.append(cur)
                cur = []
        if len(cur) >= 2:
            out.append(cur)
    return [pl for pl in out if len(pl) >= 2]


def apply_break(lines: list[Polyline], ua: float, ub: float, gap: float) -> list[Polyline]:
    """Conventional break: drop what lies between ua and ub (projector x) and move the far part back so the
    two cut ends are ``gap`` apart."""
    out: list[Polyline] = []
    for pl in lines:
        for keep_left in (True, False):
            cur: Polyline = []
            for a, b in zip(pl, pl[1:]):
                lim = ua if keep_left else ub
                ins_a = a[0] <= lim if keep_left else a[0] >= lim
                ins_b = b[0] <= lim if keep_left else b[0] >= lim
                if ins_a and ins_b:
                    cur = cur or [a]
                    cur.append(b)
                    continue
                if ins_a or ins_b:
                    t = (lim - a[0]) / (b[0] - a[0])
                    m = (lim, a[1] + t * (b[1] - a[1]))
                    if ins_a:
                        cur = cur or [a]
                        cur.append(m)
                        out.append(cur)
                        cur = []
                    else:
                        cur = [m, b]
                elif cur:
                    out.append(cur)
                    cur = []
            if len(cur) >= 2:
                out.append(cur)
    shift = (ub - ua) - gap
    return [[(x - shift, y) if x >= ub - 1e-9 else (x, y) for x, y in pl] for pl in out if len(pl) >= 2]
