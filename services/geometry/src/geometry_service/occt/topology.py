"""Indexed B-Rep topology with adjacency, built once per analysis."""

from __future__ import annotations

from dataclasses import dataclass, field

from OCP.BRep import BRep_Tool
from OCP.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_SHELL,
    TopAbs_SOLID,
    TopAbs_VERTEX,
)
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS, TopoDS_Edge, TopoDS_Face, TopoDS_Shape, TopoDS_Solid, TopoDS_Vertex

from geometry_service.occt.compat import ShapeListMap, ShapeMap


def _map(shape: TopoDS_Shape, kind) -> ShapeMap:
    m = ShapeMap()
    TopExp.MapShapes_s(shape, kind, m)
    return m


@dataclass
class TopologyIndex:
    """1-based indices, exactly as OCCT's IndexedMap assigns them."""

    shape: TopoDS_Shape
    solids: list[TopoDS_Solid] = field(default_factory=list)
    shells_count: int = 0
    faces: list[TopoDS_Face] = field(default_factory=list)
    edges: list[TopoDS_Edge] = field(default_factory=list)
    vertices: list[TopoDS_Vertex] = field(default_factory=list)
    # adjacency (0-based list positions)
    edge_faces: list[list[int]] = field(default_factory=list)
    face_edges: list[list[int]] = field(default_factory=list)
    edge_vertices: list[list[int]] = field(default_factory=list)
    face_solid: list[int | None] = field(default_factory=list)
    _face_map: ShapeMap | None = None
    _edge_map: ShapeMap | None = None
    _vertex_map: ShapeMap | None = None

    @classmethod
    def build(cls, shape: TopoDS_Shape) -> "TopologyIndex":
        idx = cls(shape=shape)
        solid_map = _map(shape, TopAbs_SOLID)
        idx.solids = [TopoDS.Solid(solid_map.FindKey(i)) for i in range(1, solid_map.Size() + 1)]
        idx.shells_count = _map(shape, TopAbs_SHELL).Size()
        fm, em, vm = _map(shape, TopAbs_FACE), _map(shape, TopAbs_EDGE), _map(shape, TopAbs_VERTEX)
        idx._face_map, idx._edge_map, idx._vertex_map = fm, em, vm
        idx.faces = [TopoDS.Face(fm.FindKey(i)) for i in range(1, fm.Size() + 1)]
        idx.edges = [TopoDS.Edge(em.FindKey(i)) for i in range(1, em.Size() + 1)]
        idx.vertices = [TopoDS.Vertex(vm.FindKey(i)) for i in range(1, vm.Size() + 1)]

        anc = ShapeListMap()
        TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, anc)
        idx.edge_faces = [[] for _ in idx.edges]
        idx.face_edges = [[] for _ in idx.faces]
        for i in range(1, anc.Size() + 1):
            e = em.FindIndex(anc.FindKey(i)) - 1
            if e < 0:
                continue
            for f_shape in anc.FindFromIndex(i):
                f = fm.FindIndex(f_shape) - 1
                if f >= 0 and f not in idx.edge_faces[e]:
                    idx.edge_faces[e].append(f)
        for e, faces in enumerate(idx.edge_faces):
            faces.sort()
            for f in faces:
                idx.face_edges[f].append(e)

        idx.edge_vertices = []
        for edge in idx.edges:
            vs = sorted({vm.FindIndex(v) - 1 for v in _vertices_of(edge, vm)} - {-1})
            idx.edge_vertices.append(vs)

        idx.face_solid = [None] * len(idx.faces)
        for s_i, solid in enumerate(idx.solids):
            sfm = _map(solid, TopAbs_FACE)
            for j in range(1, sfm.Size() + 1):
                f = fm.FindIndex(sfm.FindKey(j)) - 1
                if f >= 0 and idx.face_solid[f] is None:
                    idx.face_solid[f] = s_i
        return idx

    def adjacent_faces(self, f: int) -> list[int]:
        out: set[int] = set()
        for e in self.face_edges[f]:
            out.update(x for x in self.edge_faces[e] if x != f)
        return sorted(out)

    def is_seam(self, e: int) -> bool:
        faces = self.edge_faces[e]
        return len(faces) == 1 and BRep_Tool.IsClosed_s(self.edges[e], self.faces[faces[0]])

    def is_degenerated(self, e: int) -> bool:
        return BRep_Tool.Degenerated_s(self.edges[e])


def _vertices_of(edge: TopoDS_Edge, vm: ShapeMap):
    m = ShapeMap()
    TopExp.MapShapes_s(edge, TopAbs_VERTEX, m)
    return [m.FindKey(i) for i in range(1, m.Size() + 1)]
