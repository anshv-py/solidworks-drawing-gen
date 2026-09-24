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
