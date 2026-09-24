"""Preview mesh for the 3D viewer: one triangle group per B-Rep face, plus edge polylines.

Output (JSON-serialisable):
  positions: flat [x,y,z,...] (mm), indices: flat triangle indices,
  groups: [{face_id, start, count}] (index ranges), edges: [{edge_id, points: flat}]
"""

from __future__ import annotations

import math

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopAbs import TopAbs_REVERSED
from OCP.TopLoc import TopLoc_Location

from geometry_schema import Convexity, CurveType, GeometryIR
from geometry_service.occt import geom as g
from geometry_service.occt.topology import TopologyIndex

ROUND = 4


def brep_preview(shape, ir: GeometryIR, angular_deflection: float = 0.35) -> dict:
    lo, hi = g.bounding_box(shape)
    diag = max(g.dist(lo, hi), 1e-6)
    BRepMesh_IncrementalMesh(shape, diag * 1e-3, False, angular_deflection, True)
    topo = TopologyIndex.build(shape)
    face_ids = {f.index: f.id for f in ir.faces}
    edge_ids = {e.index: e.id for e in ir.edges}

    positions: list[float] = []
    indices: list[int] = []
    groups = []
    for i, face in enumerate(topo.faces):
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None:
            continue
        trsf = loc.Transformation()
        base = len(positions) // 3
        for n in range(1, tri.NbNodes() + 1):
            p = tri.Node(n).Transformed(trsf)
            positions.extend((round(p.X(), ROUND), round(p.Y(), ROUND), round(p.Z(), ROUND)))
        start = len(indices)
        reversed_ = face.Orientation() == TopAbs_REVERSED
        for t in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(t).Get()
            if reversed_:
                b, c = c, b
            indices.extend((base + a - 1, base + b - 1, base + c - 1))
        groups.append({"face_id": face_ids[i + 1], "start": start, "count": len(indices) - start})

    edges = []
    for i, edge in enumerate(topo.edges):
        # seams of periodic faces are parametrisation artefacts, not model edges
        if BRep_Tool.Degenerated_s(edge) or ir.edges[i].convexity == Convexity.SEAM:
            continue
        c = BRepAdaptor_Curve(edge)
        f, l = c.FirstParameter(), c.LastParameter()
        ctype = ir.edges[i].curve_type
        if ctype == CurveType.LINE:
            n = 1
        else:
            n = int(min(128, max(8, math.ceil(ir.edges[i].length / (diag * 0.01)))))
        pts: list[float] = []
        for k in range(n + 1):
            p = c.Value(f + (l - f) * k / n)
            pts.extend((round(p.X(), ROUND), round(p.Y(), ROUND), round(p.Z(), ROUND)))
        edges.append({"edge_id": edge_ids[i + 1], "points": pts})
    return {
        "format": "cad-drawing-ai/preview-mesh@1",
        "units": "mm",
        "positions": positions,
        "indices": indices,
        "groups": groups,
        "edges": edges,
    }


def stl_preview(nodes: np.ndarray, tris: np.ndarray) -> dict:
    return {
        "format": "cad-drawing-ai/preview-mesh@1",
        "units": "mm",
        "positions": [round(float(x), ROUND) for x in nodes.reshape(-1)],
        "indices": [int(x) for x in tris.reshape(-1)],
        "groups": [],
        "edges": [],
    }
