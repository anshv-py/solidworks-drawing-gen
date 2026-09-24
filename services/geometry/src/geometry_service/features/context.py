"""Shared state for the feature recognizers."""

from __future__ import annotations

from dataclasses import dataclass, field

from OCP.BRepTools import BRepTools
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp

from geometry_schema import Convexity, SurfaceType
from geometry_service.occt import geom as g
from geometry_service.occt.compat import ShapeMap
from geometry_service.occt.convexity import PointClassifier
from geometry_service.occt.faces import EdgeInfo, FaceInfo
from geometry_service.occt.topology import TopologyIndex


@dataclass
class Tolerances:
    linear: float  # mm - equality of lengths/positions
    angular_deg: float  # parallelism
    probe: float  # mm - probe step for point classification


@dataclass
class RecognitionContext:
    topo: TopologyIndex
    faces: list[FaceInfo]
    edges: list[EdgeInfo]
    convexity: list[Convexity]
    face_ids: list[str]
    edge_ids: list[str]
    classifiers: list[PointClassifier]  # one per solid
    tol: Tolerances
    claimed_faces: set[int] = field(default_factory=set)

    # ------------------------------------------------------------------ helpers

    def classifier_for_face(self, f: int) -> PointClassifier | None:
        s = self.topo.face_solid[f]
        return None if s is None else self.classifiers[s]

    def face_points(self, f: int) -> list[g.Vec]:
        """Deterministic sample of boundary points: edge start/mid/end of every edge."""
        pts: list[g.Vec] = []
        for e in self.topo.face_edges[f]:
            ei = self.edges[e]
            pts.extend((ei.start, ei.mid, ei.end))
        return pts

    def outer_wire_edges(self, f: int) -> list[int]:
        wire = BRepTools.OuterWire_s(self.topo.faces[f])
        m = ShapeMap()
        TopExp.MapShapes_s(wire, TopAbs_EDGE, m)
        out = []
        for i in range(1, m.Size() + 1):
            idx = self.topo._edge_map.FindIndex(m.FindKey(i)) - 1  # noqa: SLF001
            if idx >= 0:
                out.append(idx)
        return sorted(set(out))

    def neighbour_across(self, f: int, e: int) -> int | None:
        others = [x for x in self.topo.edge_faces[e] if x != f]
        return others[0] if others else None

    def edges_between(self, a: int, b: int) -> list[int]:
        return [e for e in self.topo.face_edges[a] if b in self.topo.edge_faces[e]]

    def is_type(self, f: int, t: SurfaceType) -> bool:
        return self.faces[f].surface_type == t

    def ids(self, faces: list[int]) -> list[str]:
        return sorted(self.face_ids[f] for f in faces)

    def eids(self, edges: list[int]) -> list[str]:
        return sorted(self.edge_ids[e] for e in edges)

    def signatures(self, faces: list[int]) -> list[str]:
        return [self.faces[f].signature for f in faces]
