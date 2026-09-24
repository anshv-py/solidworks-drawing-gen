# Example - reporting STL-derived values

Input: `bracket.stl` (binary, 12 480 triangles, watertight).

Correct:
> Overall size 80.00 × 40.00 × 30.00 mm (from mesh bounding box, confidence 0.95:
> exact for the tessellation, but the tessellation approximates the design surface).
> Hole-like openings: not recognized - STL feature recognition not yet implemented.

Incorrect:
> Hole Ø8.00 H7 (← diameter fitted from facets presented as exact, tolerance invented)

Rules: state representation = TESSELLATED, attach confidence, never add
tolerance classes, prefer "approx." wording in UI for fitted values.
