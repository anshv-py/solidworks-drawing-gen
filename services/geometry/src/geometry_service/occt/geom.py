"""Small geometric helpers on top of OCP (pure functions, mm units)."""

from __future__ import annotations

import math

from OCP.Bnd import Bnd_Box
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Dir, gp_Pnt, gp_Vec
from OCP.TopAbs import TopAbs_REVERSED
from OCP.TopoDS import TopoDS_Face, TopoDS_Shape

Vec = tuple[float, float, float]


def pnt(p: gp_Pnt) -> Vec:
    return (p.X(), p.Y(), p.Z())


def dvec(d: gp_Dir | gp_Vec) -> Vec:
    return (d.X(), d.Y(), d.Z())


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec) -> Vec:
    n = norm(a)
    if n == 0.0:
        raise ValueError("zero-length vector")
    return (a[0] / n, a[1] / n, a[2] / n)


def dist(a: Vec, b: Vec) -> float:
    return norm(sub(a, b))


def angle_deg(a: Vec, b: Vec) -> float:
    c = max(-1.0, min(1.0, dot(unit(a), unit(b))))
    return math.degrees(math.acos(c))


def parallel(a: Vec, b: Vec, tol_deg: float) -> bool:
    """True if a and b are parallel or anti-parallel within tol."""
    c = abs(dot(unit(a), unit(b)))
    return c >= math.cos(math.radians(tol_deg))


def canonical_direction(d: Vec) -> Vec:
    """Flip d so that its first significant component is positive (for grouping/hashing)."""
    for c in d:
        if abs(c) > 1e-9:
            return d if c > 0 else scale(d, -1.0)
    return d


def point_line_distance(p: Vec, origin: Vec, direction: Vec) -> float:
    v = sub(p, origin)
    d = unit(direction)
    return norm(sub(v, scale(d, dot(v, d))))


def project_on_axis(p: Vec, origin: Vec, direction: Vec) -> float:
    return dot(sub(p, origin), unit(direction))


def bounding_box(shape: TopoDS_Shape) -> tuple[Vec, Vec]:
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    return pnt(box.CornerMin()), pnt(box.CornerMax())


def volume_properties(shape: TopoDS_Shape) -> GProp_GProps:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props


def surface_properties(shape: TopoDS_Shape) -> GProp_GProps:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    return props


def face_uv_bounds(face: TopoDS_Face) -> tuple[float, float, float, float]:
    """(umin, umax, vmin, vmax) of the face's trimmed parameter domain."""
    return BRepTools.UVBounds_s(face)


def face_normal_at(face: TopoDS_Face, u: float, v: float) -> tuple[Vec, Vec] | None:
    """Point and *outward* unit normal (face orientation applied) at (u, v)."""
    surf = BRepAdaptor_Surface(face)
    props = BRepLProp_SLProps(surf, u, v, 1, 1e-9)
    if not props.IsNormalDefined():
        return None
    n = props.Normal()
    if face.Orientation() == TopAbs_REVERSED:
        n.Reverse()
    return pnt(props.Value()), dvec(n)
