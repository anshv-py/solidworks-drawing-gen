# Dimensioning principles

> Authored summary. Normative sources: ISO 129-1, ASME Y14.5.

1. **Completeness** - every feature's size and location is defined exactly once.
2. **No redundancy** - do not dimension a closed chain (A+B+C and overall);
   leave one link out or mark it reference `(…)` - reference dims are only
   used deliberately.
3. **True view** - dimension a feature where it appears in true size and shape
   (circle view for hole location, profile view for depth).
4. **Visible geometry** - avoid dimensioning to hidden lines; add a section.
5. **Placement** - outside the part outline, smaller dims closer to the part,
   larger further out; no dimension lines crossing extension lines if avoidable;
   uniform spacing.
6. **Diameters / radii** - full circles and cylinders get `Ø`; arcs ≤ 180° get `R`.
7. **Patterns** - `nX Ø…` callout once; locate the pattern (PCD, pitch).
8. **Overall dimensions** - width, height, depth always present.
9. **Units** - state once in the title block (mm); no unit suffix on each value.
10. **Values come from geometry** - the value on the sheet equals the GeometryIR
    measurement rounded to the display precision; rounding precision is a
    presentation setting, not a tolerance.

## What the deterministic dimension engine proposes (candidates)

overall extents · hole diameters · hole locations (to edges/other holes) ·
hole spacing & PCD · pocket L/W/depth · slot width/length · radii · diameters ·
angles · depths · thicknesses · feature-to-reference distances.

The planner chooses among candidates by ID; the compiler renders them; QA checks
for missing/duplicate/redundant ones.
