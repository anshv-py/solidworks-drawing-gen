"""Minimal, runnable example: count concave (hole) cylinder faces in a plate.

Run: python .claude/skills/occt-geometry-step/examples/hole_probe.py
"""
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as ShapeMap
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS

plate = BRepPrimAPI_MakeBox(100.0, 60.0, 10.0).Shape()
drill = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(50, 30, -1), gp_Dir(0, 0, 1)), 4.0, 12.0).Shape()
part = BRepAlgoAPI_Cut(plate, drill).Shape()

faces = ShapeMap()
TopExp.MapShapes_s(part, TopAbs_FACE, faces)
for i in range(1, faces.Size() + 1):
    face = TopoDS.Face(faces.FindKey(i))
    surf = BRepAdaptor_Surface(face)
    if surf.GetType() != GeomAbs_Cylinder:
        continue
    cyl = surf.Cylinder()
    u = (surf.FirstUParameter() + surf.LastUParameter()) / 2
    v = (surf.FirstVParameter() + surf.LastVParameter()) / 2
    props = BRepLProp_SLProps(surf, u, v, 1, 1e-6)
    n = props.Normal()
    if face.Orientation() == TopAbs_REVERSED:
        n.Reverse()
    p = props.Value()
    axis = cyl.Axis()
    to_p = gp_Vec(axis.Location(), p)
    radial = to_p - gp_Vec(axis.Direction()) * to_p.Dot(gp_Vec(axis.Direction()))
    concave = gp_Vec(n).Dot(radial) < 0
    print(f"F{i}: cylinder r={cyl.Radius():.3f} concave={concave}")
