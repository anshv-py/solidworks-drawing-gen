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
