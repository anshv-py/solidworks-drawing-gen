# Geometry pipeline and GeometryIR

## Engine
OCCT 8 via `cadquery-ocp` 8.0.1 (Python bindings). Runs only inside the analysis subprocess.

## STEP path (exact)
1. `STEPControl_Reader` → `SetSystemLengthUnit(1.0)` → shape in **mm** (file units recorded;
   mm/m/inch files verified to import identically).
2. `BRepCheck_Analyzer` validity → diagnostic `INVALID_BREP` if invalid (analysis continues, flagged).
3. Topology index (1-based OCCT indices) with edge→face and face→edge adjacency, face→solid.
4. Per face: surface type + analytic parameters (plane normal, cylinder axis/radius/concavity,
   cone half-angle/apex, sphere, torus), area, centroid. Per edge: curve type, length, endpoints,
   circle centre/radius/axis.
5. **Edge convexity** by probing: points just inside each adjacent face, midpoint classified
   against the solid (IN → convex, OUT → concave); equal normals → tangent; seams flagged.
6. Feature recognition (order matters, faces are claimed): holes → slots → bosses → fillets →
   chamfers → pockets → hole patterns.
7. Mass properties, principal axes (`GProp_PrincipalProps`), symmetry candidates
   (face-centroid reflection about global/principal planes through the bbox centre).
8. Stable IDs and GeometryIR assembly; preview tessellation (`BRepMesh`, deflection 1e-3 × diagonal).

### CAD product data (`geometry_service/step_metadata.py` → `GeometryIR.cad_metadata`)
Read from the STEP file itself (no kernel): `PRODUCT` name / id / description, the version id of
`PRODUCT_DEFINITION_FORMATION` (revision, ≤ 4 characters), `MATERIAL_DESIGNATION`, and the AP214
user-defined attributes (`PROPERTY_DEFINITION` → `REPRESENTATION` → `DESCRIPTIVE_REPRESENTATION_ITEM` /
`MEASURE_REPRESENTATION_ITEM`) that CAD systems use for custom properties (keys such as Material,
PartNo / Part Number / Number, Revision, Description, Mass / Weight). An explicit custom property wins
over `PRODUCT.id`; a `PRODUCT.id` equal to the name (the file name) is not taken as a part number.
Ignored, never used: translator placeholders ("Open CASCADE STEP translator …", Part1, None, Any),
unevaluated SolidWorks links (`"SW-Material@Part1.SLDPRT"`), several different materials, and product
identification of assemblies. Every value records its entity in `sources`. Which custom properties a real
SolidWorks / CATIA / NX export contains is UNVERIFIED (tested on synthetic AP214 files).

## STL path (tessellated)
`RWStl` → nodes/triangles; bbox, area, watertightness; volume/centroid/inertia by signed
tetrahedra when closed. Units assumed mm (warning). **No feature recognition yet**; all values
flagged `TESSELLATED`. Measured deviation on fixtures: volume within 0.5 % of exact STEP.

## Feature recognition rules (M1)
| Feature | Rule | Confidence |
|---|---|---|
| HOLE | concave cylinder faces grouped by axis/radius covering 360°; coaxial larger stage = counterbore; concave coaxial cone at open end = countersink; open/closed ends by probing past the axial extent | 0.99 simple · 0.95 stacked |
| BOSS | convex full cylinder (external Ø: bosses, shaft steps, outer diameters) | 0.90 |
| SLOT | two concave ~180° half-cylinders, equal radius, parallel axes, joined by two tangent planar walls | 0.90 |
| POCKET | planar floor whose outer-loop edges are all concave (or tangent to concave blends), not a hole bottom | 0.85 |
| FILLET | partial cylinder / torus tangent to ≥ 2 neighbours; `concave` = fillet vs round | 0.85 |
| CHAMFER | narrow planar face inclined 10-80° between two non-parallel planes (legs from the virtual sharp edge) or convex cone between a cylinder and a cap | 0.75 / 0.85 |
| PATTERN | ≥ 3 identical holes (Ø, kind, through, axis): circular (preferred when centre lies on another axis), rectangular grid, linear | 0.95 |

Tolerances: linear `max(1e-4, 1e-6·diag)` mm; angular 0.5°; probe `clamp(1e-4·diag, 1e-4, 0.05)` mm.

## Stable IDs
`FACE-<10 hex>` = sha1(surface type, area, centroid, radius/normal rounded to 1e-4 mm);
`EDGE-…` = sha1(curve type, length, midpoint, endpoints); `VTX-…` = sha1(point);
features `<TYPE>-<8 hex>` = sha1(sorted member face signatures). Identical signatures are
disambiguated deterministically (`.1`, `.2`). Verified identical across re-analysis.

## Known limitations
- Threads are not recognized (plain B-Rep has no thread geometry; needs AP242 PMI or user input).
- Non-cylindrical bosses, freeform (B-spline) features, variable fillets, pockets whose floor
  meets walls through non-concave transitions, patterns of pockets/slots, partial hole subsets.
- Multi-solid files: analysed per solid; features are not yet grouped per body in the UI.
- Coordinate frame is the file's (Z-up assumed for preview). Mapping to SolidWorks views
  (Y-up "Front") must be defined in the compiler milestone.
