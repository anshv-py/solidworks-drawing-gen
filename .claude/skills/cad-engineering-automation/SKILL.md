---
name: cad-engineering-automation
description: Engineering-drawing and CAD domain knowledge for CAD Drawing AI. Activate when reasoning about what a drawing should contain - choosing views (orthographic, isometric, section, detail, projected), deciding which dimensions/center marks/centerlines/hole callouts a part needs, interpreting B-Rep topology or recognized features (holes, slots, pockets, bosses, fillets, chamfers, patterns, threads) in engineering terms, applying ISO/ASME drawing concepts (projection method, sheet sizes, scales, title blocks), distinguishing a geometry drawing from a manufacturing drawing, or deciding how much to trust STEP vs STL data. Do NOT use for OCCT API code (use occt-geometry-step), SolidWorks API code (use solidworks-api-automation), QA check implementation (use cad-drawing-qa), or general backend/frontend engineering (use production-software-engineering).
---

# CAD Engineering Automation

Domain knowledge for turning a 3D CAD model into a correct, readable
engineering drawing. This skill answers **"what should the drawing say and
why"** - not how to call a CAD kernel or SolidWorks.

## Non-negotiable truth rules

1. **Never invent geometry.** Every coordinate, length, radius, angle and count
   comes from the geometry engine (OCCT via GeometryIR). If GeometryIR lacks a
   value, the value does not exist for the drawing.
2. **Never invent dimensions.** The planner may *select* dimension candidates
   (by ID) that the deterministic dimension engine produced. It never types a
   number.
3. **Never invent manufacturing requirements.** Material, general tolerance,
   GD&T, datums, surface finish, heat treatment, coating, inspection and
   process are `UNSPECIFIED` unless the CAD file or the user supplies them -
   and the source is recorded.
4. **The CAD geometry engine is the source of geometric truth.** The LLM
   reasons and plans; it does not measure.
5. **STEP = exact B-Rep.** Treat analytic surface parameters (plane, cylinder
   radius, cone angle) as exact to kernel tolerance.
   **STL = tessellated.** Every STL-derived measurement is *inferred*, carries
   a confidence < 1.0, and the drawing must say so. Never present an STL
   "diameter" as if it were a design value.

## Geometry drawing vs manufacturing drawing

| | Geometry drawing | Manufacturing drawing |
|---|---|---|
| Views, dimensions from model | yes | yes |
| Material, tolerances, GD&T, datums, finish | **no** - title block shows `UNSPECIFIED` | only from explicit user/CAD input |
| Default output of this product | **yes** | only when the required inputs are supplied |

A CAD model alone yields a *geometry drawing*. The attached example drawing in
`examples/reference-drawings/` is a *manufacturing* drawing (GD&T frames, datum
letters A/B/C, limit dimensions like `Ø44.60/44.45`); nearly all of that
tolerance information is **not** derivable from geometry and must never be
generated unless supplied. See `references/geometry-vs-manufacturing.md`.

## Topology vocabulary (B-Rep)

Solid → Shell(s) → Faces → Wires (loops) → Edges → Vertices. A face lies on
one surface (plane, cylinder, cone, sphere, torus, B-spline...); an edge lies
on one curve. Shared edges give face adjacency; edge convexity (convex /
concave / tangent) is what feature recognition is built on. Details:
`references/brep-and-features.md`.

## Feature semantics (what a recognized feature means on a drawing)

| Feature | Drawing treatment |
|---|---|
| Hole (simple, through/blind) | Center mark in circular view, centerline in side view, `Ø` + depth (or THRU) via hole callout, location from datum/edge |
| Counterbore / countersink | Hole callout with ⌴ / ⌵ symbols; values only from recognized sub-features |
| Hole pattern | One callout with `nX` count; pattern location (PCD or pitch) dimensioned once |
| Slot | Width, length (center-to-center or overall - pick one), location |
| Pocket | Length, width, depth, corner radius if present, location |
| Boss (cylindrical) | Diameter, height, location |
| Fillet / round | `R` value; identical fillets may use one note ("ALL FILLETS R2" only if every fillet truly is R2) |
| Chamfer | `size × angle` or `size × size` |
| Thread | Only when detected (e.g. STEP cosmetic thread / user input). A plain cylinder is **not** a thread. |

## View selection principles

- The **primary view** shows the most characteristic shape with the fewest
  hidden lines. Product default: user-selectable, default **ISOMETRIC** as a
  pictorial primary view, plus orthographic projected views for dimensioning.
- Orthographic views are for dimensioning; pictorial (isometric) views are
  normally **not** dimensioned.
- Add a **section view** when internal features (bores, blind holes, internal
  pockets) would otherwise need hidden-line dimensioning.
- Add a **detail view** when a feature is too small to dimension legibly at
  sheet scale.
- Use only as many views as needed to fully define the part.
- **Projection method** determines placement: first angle (ISO default, symbol
  per ISO 5456-2) places the top view *below* the front view and the left view
  on the *right*; third angle (ASME default) is the reverse. See
  `references/projection-and-views.md`.

## Dimensioning principles

- Every feature dimensioned **once**, in the view where it appears true size
  and shape. No duplicate or redundant (over-constrained) chains.
- Dimension to visible outlines, not hidden lines.
- Diameters in the longitudinal view for cylinders; radii where the arc is seen.
- Prefer a consistent datum scheme (baseline) over long chains. If no datum
  scheme is supplied, dimension from *geometric* references (e.g. part edges)
  and do **not** label them as datums.
- Overall width/height/depth always appear.
- Details: `references/dimensioning-principles.md`.

## Defaults for this product

ISO standard · first-angle projection · A3 landscape · mm · primary view
isometric · scale AUTO chosen from ISO 5455 preferred scales.

## How to use this skill

1. Read GeometryIR (never raw files) and the user's drawing settings.
2. Decide views, sections, details, and which dimension candidates matter.
3. Emit decisions only through the typed `DrawingPlan` schema.
4. Flag uncertainty explicitly (low-confidence features, STL input, missing
   engineering information).

## References

- `references/brep-and-features.md` - topology and feature taxonomy
- `references/projection-and-views.md` - projection, view types, placement
- `references/dimensioning-principles.md` - what/where to dimension
- `references/drawing-standards-index.md` - ISO/ASME standard index (titles only; buy/consult the standards themselves)
- `references/geometry-vs-manufacturing.md` - the non-invention rule in detail
- `examples/flange-view-plan.md` - worked reasoning for a flange
- `examples/stl-confidence.md` - how to report STL-derived values
