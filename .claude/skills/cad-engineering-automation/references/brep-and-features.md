# B-Rep topology and feature taxonomy

> Authored summary for this project. Not a copy of any standard or vendor document.

## Topology hierarchy

| Entity | Meaning | Notes |
|---|---|---|
| Compound | Arbitrary group of shapes | STEP files often wrap solids in a compound |
| CompSolid | Solids sharing faces | Rare in mechanical parts |
| Solid | Closed volume bounded by shell(s) | One outer shell + optional inner void shells |
| Shell | Connected set of faces | Closed shell => watertight |
| Face | Bounded region of one surface | Bounded by one outer wire + inner wires (holes in the face) |
| Wire | Connected loop of edges | |
| Edge | Bounded region of one curve | Shared by (usually) two faces in a manifold solid |
| Vertex | Point | |

Orientation matters: a face's outward normal is the surface normal, reversed if
the face orientation is REVERSED.

## Surface types seen in mechanical parts

| Surface | Parameters | Typical feature |
|---|---|---|
| Plane | origin, normal | faces, floors, walls, chamfers |
| Cylinder | axis, radius | holes (concave), shafts/bosses (convex), fillets (partial) |
| Cone | apex/axis, half-angle, ref radius | countersinks, conical chamfers, tapers |
| Sphere | center, radius | ball ends, spherical fillets |
| Torus | axis, major/minor radius | fillets on circular edges |
| B-spline/Bezier | control net | freeform - features rarely recognizable |

## Edge convexity

For an edge shared by faces A and B:
- **Convex**: material angle < 180° (outside corner of a block).
- **Concave**: material angle > 180° (inside corner, pocket floor/wall).
- **Tangent/smooth**: normals continuous across the edge (fillet boundaries).

Feature recognition = patterns in the face-adjacency graph labelled with
convexity and surface type.

## Feature taxonomy used in GeometryIR

| Type | Recognition signature (conceptual) |
|---|---|
| HOLE | Concave cylinder(s) covering 360°, coaxial; through if both ends open to air, blind if one end closed |
| COUNTERBORE / COUNTERSINK | Coaxial concave cylinder of larger radius / concave cone at the open end of a hole |
| BOSS | Convex full cylinder standing on a planar face |
| POCKET | Planar floor whose boundary edges are all concave, with walls rising to an opening |
| SLOT | Pocket (or through cut) with two parallel walls and two semicircular ends of equal radius |
| FILLET | Partial cylinder/torus tangent to both neighbours |
| CHAMFER | Narrow plane (or cone) meeting both neighbours at non-tangent edges, bevelling a former edge |
| PATTERN | ≥ N identical features arranged linearly, rectangularly, or on a circle |
| THREAD | Not geometric in most B-Reps (cosmetic). Only from explicit metadata. |

Recognition is **heuristic**; every recognized feature carries a confidence and
the IDs of the faces it came from so humans can verify it.
