# Worked example - flange (compare `examples/reference-drawings/` in the repo)

GeometryIR summary (from the `flange` fixture - values are the fixture's
construction parameters, verified by OCCT extraction in tests):
- outer Ø100 disk, 10 mm thick; hub Ø45 × 30 mm; through bore Ø20
- 8 × Ø8 through holes, circular pattern on Ø86 PCD, 45° spacing
- axis = Z

Reasoning:
1. Turned/axisymmetric part → axis horizontal in the front view.
2. Internal bore → **full section** as the front view (A-A through the axis),
   like the reference drawing's left view.
3. Circular view (along axis) shows the bolt pattern → end view, placed per
   projection method (first angle: view from the left goes on the right).
4. Primary pictorial: isometric (product default), not dimensioned.
5. Dimension candidates chosen: overall Ø100, flange thickness, hub Ø45, hub
   length, bore Ø20, pattern `8X Ø8 THRU EQ SP on Ø86` (single callout + PCD).
6. Center marks on all 8 holes and the bore in the end view; centerline on the
   axis in the section.
7. Title block: material, tolerances, finish → `UNSPECIFIED`. The reference
   drawing's GD&T (position Ø0.14 Ⓜ A C Ⓜ, etc.) is **not** reproduced because
   it was not supplied.
