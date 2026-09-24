# OCP (cadquery-ocp 8.0.1) calls verified in this environment

Probed on 2026-09-24 (Python 3.12, Linux x86_64) with `dir()`, `__doc__` and
by running the repo's test-suite.

| Purpose | Call |
|---|---|
| Read STEP | `r = STEPControl_Reader(); r.ReadFile(path) == IFSelect_RetDone; r.TransferRoots(); r.OneShape()` |
| Units | `r.SetSystemLengthUnit(1.0)` (mm; call after ReadFile, "performs only if a model is not NULL"); `r.FileUnits(seqLen, seqAng, seqSolid)` with `OCP.OCP.collections.Sequence_TCollection_AsciiString` |
| Write STEP (fixtures) | `STEPControl_Writer().Transfer(shape, STEPControl_AsIs); .Write(path)`; unit via `Interface_Static.SetCVal_s("write.step.unit", "M")` |
| Validity | `BRepCheck_Analyzer(shape).IsValid()` |
| Index sub-shapes | `m = IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher(); TopExp.MapShapes_s(shape, TopAbs_FACE, m); m.Size(); m.FindKey(i)` (1-based); `m.FindIndex(s)` |
| Ancestors | `d = IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher(); TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, d)`; `d.FindFromIndex(i)` → `List_TopoDS_Shape` (iterable) |
| Downcast | `TopoDS.Face(s)`, `TopoDS.Edge(s)`, `TopoDS.Vertex(s)`, `TopoDS.Solid(s)` (namespace functions - **no** `_s` suffix) |
| Mass props | `p = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, p)`; `p.Mass()`, `p.CentreOfMass()`, `p.PrincipalProperties()`; `BRepGProp.SurfaceProperties_s`, `LinearProperties_s` |
| Bounding box | `b = Bnd_Box(); BRepBndLib.AddOptimal_s(shape, b, False, False); b.Get()` |
| Surface type | `BRepAdaptor_Surface(face).GetType()` → `GeomAbs_Plane/Cylinder/Cone/Sphere/Torus/...`; `.Cylinder()` → `gp_Cylinder` (`Radius()`, `Axis()`), `.Plane()`, `.Cone()`, `.Torus()`, `.Sphere()`; `FirstUParameter()/LastUParameter()` |
| Point classification | `BRepClass3d_SolidClassifier(solid, gp_Pnt, tol).State()` → `TopAbs_IN/OUT/ON` |
| Tessellation | `BRepMesh_IncrementalMesh(shape, lin_defl, False, ang_defl, True)`; `BRep_Tool.Triangulation_s(face, TopLoc_Location)` |
| STL read | `RWStl.ReadFile_s(path)` → `Poly_Triangulation` |

## Gotchas
- `TopTools_IndexedMapOfShape` & friends are absent in OCP 8 - use `OCP.OCP.collections`.
- `Standard_Version` is not exposed; read version from package metadata.
- Face orientation: outward normal = surface normal × (-1 if `face.Orientation() == TopAbs_REVERSED`).
- STEP split periodic faces: one hole is often 2 half-cylinder faces - group coaxial equal-radius faces.
