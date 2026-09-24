"""Face / edge / vertex descriptors computed from OCCT (the numbers in GeometryIR)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRep import BRep_Tool
from OCP.BRepTools import BRepTools
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GeomAbs import (
    GeomAbs_BezierCurve,
    GeomAbs_BezierSurface,
    GeomAbs_BSplineCurve,
    GeomAbs_BSplineSurface,
    GeomAbs_Circle,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Ellipse,
    GeomAbs_Hyperbola,
    GeomAbs_Line,
    GeomAbs_OffsetCurve,
    GeomAbs_OffsetSurface,
    GeomAbs_Parabola,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_SurfaceOfExtrusion,
    GeomAbs_SurfaceOfRevolution,
    GeomAbs_Torus,
)
from OCP.TopoDS import TopoDS_Edge, TopoDS_Face, TopoDS_Vertex

from geometry_schema import CurveType, SurfaceType
from geometry_service.occt import geom as g

_SURFACE_TYPES = {
    GeomAbs_Plane: SurfaceType.PLANE,
    GeomAbs_Cylinder: SurfaceType.CYLINDER,
    GeomAbs_Cone: SurfaceType.CONE,
    GeomAbs_Sphere: SurfaceType.SPHERE,
    GeomAbs_Torus: SurfaceType.TORUS,
    GeomAbs_BSplineSurface: SurfaceType.BSPLINE,
    GeomAbs_BezierSurface: SurfaceType.BEZIER,
    GeomAbs_SurfaceOfRevolution: SurfaceType.REVOLUTION,
    GeomAbs_SurfaceOfExtrusion: SurfaceType.EXTRUSION,
    GeomAbs_OffsetSurface: SurfaceType.OFFSET,
}

_CURVE_TYPES = {
    GeomAbs_Line: CurveType.LINE,
    GeomAbs_Circle: CurveType.CIRCLE,
    GeomAbs_Ellipse: CurveType.ELLIPSE,
    GeomAbs_Hyperbola: CurveType.HYPERBOLA,
    GeomAbs_Parabola: CurveType.PARABOLA,
    GeomAbs_BezierCurve: CurveType.BEZIER,
    GeomAbs_BSplineCurve: CurveType.BSPLINE,
    GeomAbs_OffsetCurve: CurveType.OFFSET,
}


@dataclass
class FaceInfo:
    index: int  # 0-based position in TopologyIndex.faces
    surface_type: SurfaceType
    area: float
    centroid: g.Vec
    # analytic parameters (subset filled per type)
    normal: g.Vec | None = None  # plane outward normal
    origin: g.Vec | None = None  # plane origin / axis origin / sphere centre
    axis_dir: g.Vec | None = None
    radius: float | None = None  # cylinder / sphere / cone reference radius / torus major
    minor_radius: float | None = None  # torus
    half_angle_deg: float | None = None  # cone
    apex: g.Vec | None = None  # cone
    concave: bool | None = None  # cylinder / cone / sphere: material outside the surface
    angular_extent_deg: float | None = None
    vertex_points: list[g.Vec] = field(default_factory=list)
    signature: str = ""


@dataclass
class EdgeInfo:
    index: int
    curve_type: CurveType
    length: float
    start: g.Vec
    end: g.Vec
    mid: g.Vec
    circle_center: g.Vec | None = None
    circle_radius: float | None = None
    circle_axis: g.Vec | None = None
    signature: str = ""


def _concave_about_axis(face: TopoDS_Face, axis_origin: g.Vec, axis_dir: g.Vec) -> bool | None:
    """True if the outward normal points toward the axis (material outside -> hole-like)."""
    res = g.face_normal_at(face, *_mid_uv(face))
    if res is None:
        return None
    p, n = res
    v = g.sub(p, axis_origin)
    radial = g.sub(v, g.scale(axis_dir, g.dot(v, axis_dir)))
    if g.norm(radial) < 1e-9:
        return None
    return g.dot(n, radial) < 0


def describe_face(index: int, face: TopoDS_Face) -> FaceInfo:
    surf = BRepAdaptor_Surface(face)
    stype = _SURFACE_TYPES.get(surf.GetType(), SurfaceType.OTHER)
    props = g.surface_properties(face)
    info = FaceInfo(
        index=index,
        surface_type=stype,
        area=props.Mass(),
        centroid=g.pnt(props.CentreOfMass()),
    )
    umin, umax, _, _ = BRepTools.UVBounds_s(face)
    if stype == SurfaceType.PLANE:
        pl = surf.Plane()
        info.origin = g.pnt(pl.Location())
        n = g.dvec(pl.Axis().Direction())
        # orientation-aware outward normal
        res = g.face_normal_at(face, *_mid_uv(face))
        info.normal = res[1] if res else n
    elif stype == SurfaceType.CYLINDER:
        c = surf.Cylinder()
        ax = c.Axis()
        info.origin, info.axis_dir, info.radius = g.pnt(ax.Location()), g.dvec(ax.Direction()), c.Radius()
        info.concave = _concave_about_axis(face, info.origin, info.axis_dir)
        info.angular_extent_deg = math.degrees(umax - umin)
    elif stype == SurfaceType.CONE:
        c = surf.Cone()
        ax = c.Axis()
        info.origin, info.axis_dir = g.pnt(ax.Location()), g.dvec(ax.Direction())
        info.radius, info.half_angle_deg = c.RefRadius(), math.degrees(c.SemiAngle())
        info.apex = g.pnt(c.Apex())
        info.concave = _concave_about_axis(face, info.origin, info.axis_dir)
        info.angular_extent_deg = math.degrees(umax - umin)
    elif stype == SurfaceType.SPHERE:
        sp = surf.Sphere()
        info.origin, info.radius = g.pnt(sp.Location()), sp.Radius()
        res = g.face_normal_at(face, *_mid_uv(face))
        if res:
            p, n = res
            info.concave = g.dot(n, g.sub(p, info.origin)) < 0
    elif stype == SurfaceType.TORUS:
        t = surf.Torus()
        ax = t.Axis()
        info.origin, info.axis_dir = g.pnt(ax.Location()), g.dvec(ax.Direction())
        info.radius, info.minor_radius = t.MajorRadius(), t.MinorRadius()
        info.angular_extent_deg = math.degrees(umax - umin)
        res = g.face_normal_at(face, *_mid_uv(face))
        if res:
            p, n = res
            v = g.sub(p, info.origin)
            radial = g.sub(v, g.scale(info.axis_dir, g.dot(v, info.axis_dir)))
            if g.norm(radial) > 1e-9:
                tube_centre = g.add(info.origin, g.scale(g.unit(radial), info.radius))
                # material outside the tube -> concave blend (fillet in an inside corner)
                info.concave = g.dot(n, g.sub(p, tube_centre)) < 0
    return info


def _mid_uv(face: TopoDS_Face) -> tuple[float, float]:
    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
    return 0.5 * (umin + umax), 0.5 * (vmin + vmax)


def describe_edge(index: int, edge: TopoDS_Edge) -> EdgeInfo:
    c = BRepAdaptor_Curve(edge)
    ctype = _CURVE_TYPES.get(c.GetType(), CurveType.OTHER)
    f, l = c.FirstParameter(), c.LastParameter()
    try:
        length = GCPnts_AbscissaPoint.Length_s(c)
    except Exception:  # degenerate edges
        length = 0.0
    info = EdgeInfo(
        index=index,
        curve_type=ctype,
        length=length,
        start=g.pnt(c.Value(f)),
        end=g.pnt(c.Value(l)),
        mid=g.pnt(c.Value(0.5 * (f + l))),
    )
    if ctype == CurveType.CIRCLE:
        circ = c.Circle()
        info.circle_center = g.pnt(circ.Location())
        info.circle_radius = circ.Radius()
        info.circle_axis = g.canonical_direction(g.dvec(circ.Axis().Direction()))
    return info


def vertex_point(v: TopoDS_Vertex) -> g.Vec:
    return g.pnt(BRep_Tool.Pnt_s(v))
