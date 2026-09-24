"""Edge convexity by in-face probing and 3D point classification.

For an edge shared by faces A and B we take the edge mid point P, step a small
distance into each face (perpendicular to the edge, inside the trimmed face)
to get Qa and Qb, and classify the midpoint of Qa/Qb against the solid:
IN  -> the faces meet at a CONVEX edge (material between them),
OUT -> CONCAVE. Faces whose normals agree at P are TANGENT (smooth).
This avoids any dependence on edge/wire orientation conventions.
"""

from __future__ import annotations

from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRep import BRep_Tool
from OCP.gp import gp_Pnt
from OCP.ShapeAnalysis import ShapeAnalysis_Surface
from OCP.TopAbs import TopAbs_IN, TopAbs_ON, TopAbs_OUT
from OCP.TopoDS import TopoDS_Edge, TopoDS_Face, TopoDS_Shape

from geometry_schema import Convexity
from geometry_service.occt import geom as g


class PointClassifier:
    """Reusable solid classifier (IN / OUT / ON)."""

    def __init__(self, solid: TopoDS_Shape, tol: float) -> None:
        self._clf = BRepClass3d_SolidClassifier(solid)
        self._tol = tol

    def state(self, p: g.Vec):
        self._clf.Perform(gp_Pnt(*p), self._tol)
        return self._clf.State()

    def inside(self, p: g.Vec) -> bool:
        return self.state(p) == TopAbs_IN

    def outside(self, p: g.Vec) -> bool:
        return self.state(p) == TopAbs_OUT


def edge_midpoint_and_tangent(edge: TopoDS_Edge) -> tuple[g.Vec, g.Vec] | None:
    curve = BRepAdaptor_Curve(edge)
    t = 0.5 * (curve.FirstParameter() + curve.LastParameter())
    p = gp_Pnt()
    from OCP.gp import gp_Vec

    v = gp_Vec()
    curve.D1(t, p, v)
    if v.Magnitude() < 1e-12:
        return None
    return g.pnt(p), g.unit(g.dvec(v))


def face_normal_at_point(face: TopoDS_Face, p: g.Vec) -> g.Vec | None:
    surf = BRep_Tool.Surface_s(face)
    uv = ShapeAnalysis_Surface(surf).ValueOfUV(gp_Pnt(*p), 1e-7)
    res = g.face_normal_at(face, uv.X(), uv.Y())
    return None if res is None else res[1]


def in_face_probe(face: TopoDS_Face, p: g.Vec, tangent: g.Vec, eps: float) -> g.Vec | None:
    """A point ~eps from p, inside the trimmed face, stepping perpendicular to the edge."""
    n = face_normal_at_point(face, p)
    if n is None:
        return None
    try:
        d = g.unit(g.cross(n, tangent))
    except ValueError:
        return None
    surf = ShapeAnalysis_Surface(BRep_Tool.Surface_s(face))
    for sign in (1.0, -1.0):
        q = g.add(p, g.scale(d, sign * eps))
        # snap onto the surface so curved faces are probed on-surface
        uv = surf.ValueOfUV(gp_Pnt(*q), 1e-7)
        q_on = g.pnt(surf.Value(uv.X(), uv.Y()))
        state = BRepClass_FaceClassifier(face, gp_Pnt(*q_on), 1e-7).State()
        if state == TopAbs_IN:
            return q_on
    return None


def classify_edge(
    edge: TopoDS_Edge,
    face_a: TopoDS_Face,
    face_b: TopoDS_Face,
    classifier: PointClassifier,
    eps: float,
    tangent_tol_deg: float = 1.0,
) -> Convexity:
    mt = edge_midpoint_and_tangent(edge)
    if mt is None:
        return Convexity.UNKNOWN
    p, t = mt
    na, nb = face_normal_at_point(face_a, p), face_normal_at_point(face_b, p)
    if na is not None and nb is not None and g.angle_deg(na, nb) < tangent_tol_deg:
        return Convexity.TANGENT
    qa, qb = in_face_probe(face_a, p, t, eps), in_face_probe(face_b, p, t, eps)
    if qa is None or qb is None:
        return Convexity.UNKNOWN
    state = classifier.state(g.scale(g.add(qa, qb), 0.5))
    if state == TopAbs_IN:
        return Convexity.CONVEX
    if state == TopAbs_OUT:
        return Convexity.CONCAVE
    if state == TopAbs_ON:
        return Convexity.TANGENT
    return Convexity.UNKNOWN
