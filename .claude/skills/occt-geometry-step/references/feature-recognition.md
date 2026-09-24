# Feature recognition algorithms (milestone 1)

All rules operate on the indexed face-adjacency graph with edge convexity.

## Edge convexity
For edge E shared by faces A, B: find point P at mid-parameter of E; for each
face find an interior point Qa, Qb at distance ε from P inside the face
(pcurve-normal probe classified with the 2D face classifier). If the midpoint
of Qa, Qb is IN the solid → CONVEX, OUT → CONCAVE. If face normals at P
differ by < 1° → TANGENT (smooth).

## Holes (confidence 0.99 for exact analytic data)
1. Collect cylindrical faces; outward normal at a sample point vs radial
   vector from axis: pointing toward axis → concave (internal).
2. Group concave cylinder faces by (axis line, radius) within tolerance;
   group's angular coverage must be 2π.
3. Coaxial groups with different radii form a stack (counterbore).
   Concave cones coaxial at an end → countersink / chamfered entry.
4. Axial extent from projecting face vertices on the axis.
5. Each open end: probe point ε beyond the end on the axis → OUT ⇒ open.
   Both open ⇒ THROUGH; one ⇒ BLIND (depth = axial length).

## Bosses (0.9)
Convex full-coverage cylinder group. Top/bottom planar caps recorded.

## Pockets / slots (0.8)
Planar face F (floor) whose every outer-wire edge is CONCAVE and whose
neighbours are walls (normals ⟂ floor normal). Depth = max projection of wall
vertices onto floor normal − floor plane offset. Slot: pocket whose walls
include exactly two concave half-cylinders of equal radius r with parallel
axes, width = 2r, length = centre distance + 2r.

## Fillets (0.85) / chamfers (0.7)
Fillet: cylinder or torus face with angular coverage < 2π, tangent to ≥ 2
neighbours. Chamfer: planar face with ≥ 2 non-tangent neighbours on opposite
sides, whose normal is inclined to both, and whose width ≪ length (aspect ≥ 3),
or a short cone coaxial with a hole/boss end.

## Patterns
Among holes of equal diameter & parallel axes (≥ 3): circular if centres
equidistant from a common centre with equal angular step (PCD reported);
linear if collinear with equal pitch; rectangular if centres form an n×m grid.
