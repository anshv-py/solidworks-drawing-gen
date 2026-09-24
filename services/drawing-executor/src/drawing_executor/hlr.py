"""Exact hidden-line removal (OCCT HLRBRep_Algo) per view, in view-plane model units.

HLR output lies in the projector plane: x along the view's x_axis, y along eye × x_axis,
origin at the projector origin (the model centre). The sheet transform (scale + offset)
is applied separately, so one HLR run serves every layout/scale attempt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GeomAbs import GeomAbs_Line
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS, TopoDS_Shape

from geometry_service.occt.compat import ShapeMap

Polyline = list[tuple[float, float]]


@dataclass
class ViewLines:
    visible: list[Polyline] = field(default_factory=list)
    hidden: list[Polyline] = field(default_factory=list)


def _polylines(compound: TopoDS_Shape | None, max_seg: float) -> list[Polyline]:
    if compound is None or compound.IsNull():
        return []
    m = ShapeMap()
    TopExp.MapShapes_s(compound, TopAbs_EDGE, m)
    out: list[Polyline] = []
    for i in range(1, m.Size() + 1):
        c = BRepAdaptor_Curve(TopoDS.Edge(m.FindKey(i)))
        f, l = c.FirstParameter(), c.LastParameter()
        if c.GetType() == GeomAbs_Line:
            n = 1
        else:
            try:
                length = GCPnts_AbscissaPoint.Length_s(c)
            except Exception:  # noqa: BLE001 - degenerate HLR fragments
                continue
            n = int(min(256, max(8, math.ceil(length / max_seg))))
        pts = []
        for k in range(n + 1):
            p = c.Value(f + (l - f) * k / n)
            pts.append((p.X(), p.Y()))
        out.append(pts)
    return out


def hidden_line_removal(shape: TopoDS_Shape, center, eye, x_axis, *, with_hidden: bool,
                        max_seg: float = 0.5) -> ViewLines:
    algo = HLRBRep_Algo()
    algo.Add(shape)
    algo.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(*center), gp_Dir(*eye), gp_Dir(*x_axis))))
    algo.Update()
    algo.Hide()
    h = HLRBRep_HLRToShape(algo)
    lines = ViewLines()
    # sharp edges + silhouettes. Smooth (tangent) edges are omitted per common ISO practice.
    lines.visible = _polylines(h.VCompound(), max_seg) + _polylines(h.OutLineVCompound(), max_seg)
    if with_hidden:
        lines.hidden = _polylines(h.HCompound(), max_seg) + _polylines(h.OutLineHCompound(), max_seg)
    return lines


@dataclass
class Facet:
    points: list[tuple[float, float]]  # projected triangle (projector-plane coordinates)
    shade: float  # 0 (dark) .. 1 (light)
    depth: float  # distance toward the viewer (larger = nearer)


def shaded_facets(shape: TopoDS_Shape, center, eye, x_axis, *, deflection: float | None = None) -> list[Facet]:
    """Flat-shaded, back-face-culled triangles for a pictorial view, sorted far → near.

    Drawn in this order (painter's algorithm) and overdrawn by the exact HLR edges, this gives
    the 'shaded with edges' look of the reference drawings. Pure display: never used for
    measurement.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location

    from geometry_service.occt import geom as g

    lo, hi = g.bounding_box(shape)
    diag = max(g.dist(lo, hi), 1e-6)
    BRepMesh_IncrementalMesh(shape, deflection or diag * 2e-3, False, 0.3, True)
    e = _unit(eye)
    xa = _unit(x_axis)
    ya = _cross(e, xa)
    light = _unit((e[0] + 0.35 * ya[0] - 0.3 * xa[0], e[1] + 0.35 * ya[1] - 0.3 * xa[1],
                   e[2] + 0.35 * ya[2] - 0.3 * xa[2]))
    m = ShapeMap()
    TopExp.MapShapes_s(shape, TopAbs_FACE, m)
    out: list[Facet] = []
    for i in range(1, m.Size() + 1):
        face = TopoDS.Face(m.FindKey(i))
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None:
            continue
        trsf = loc.Transformation()
        nodes = []
        for n in range(1, tri.NbNodes() + 1):
            p = tri.Node(n).Transformed(trsf)
            nodes.append((p.X() - center[0], p.Y() - center[1], p.Z() - center[2]))
        rev = face.Orientation() == TopAbs_REVERSED
        for t in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(t).Get()
            if rev:
                b, c = c, b
            pa, pb, pc = nodes[a - 1], nodes[b - 1], nodes[c - 1]
            nrm = _cross(_sub3(pb, pa), _sub3(pc, pa))
            ln = math.sqrt(_dot(nrm, nrm))
            if ln < 1e-12:
                continue
            nrm = (nrm[0] / ln, nrm[1] / ln, nrm[2] / ln)
            if _dot(nrm, e) <= 1e-6:  # facing away
                continue
            shade = 0.25 + 0.75 * max(0.0, _dot(nrm, light))
            pts = [(_dot(p, xa), _dot(p, ya)) for p in (pa, pb, pc)]
            depth = (_dot(pa, e) + _dot(pb, e) + _dot(pc, e)) / 3
            out.append(Facet(points=pts, shade=round(shade, 3), depth=depth))
    out.sort(key=lambda f: f.depth)
    return out


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _unit(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)
