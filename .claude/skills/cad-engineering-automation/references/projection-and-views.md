# Projection methods and view types

> Authored summary. Consult ISO 5456-2 / ISO 128-3 (or ASME Y14.3) for normative text.

## First-angle vs third-angle placement (relative to the FRONT view)

| View (direction of sight) | First angle (ISO default) | Third angle (ASME default) |
|---|---|---|
| Top (from above) | below front | above front |
| Bottom (from below) | above front | below front |
| Left (from left) | right of front | left of front |
| Right (from right) | left of front | right of front |
| Rear | far right or far left | far right or far left |

The projection symbol (truncated cone) must appear in/near the title block.

## View types

| View | Use |
|---|---|
| Orthographic (principal) | Dimensioning; true size/shape of faces parallel to the view plane |
| Isometric / pictorial | Readability; normally not dimensioned |
| Projected | Derived from a parent view along a principal direction; aligned with it |
| Auxiliary | Projected perpendicular to an inclined face to show its true shape |
| Full section | Cutting plane through the whole part; reveals internal features |
| Half section | For symmetric parts: half exterior, half section |
| Offset / aligned section | Cutting plane stepped/rotated to pass through several features |
| Broken-out section | Local section of a small region |
| Detail | Enlarged region at a larger scale, labelled with a letter and scale |

## Choosing a front view

Prefer the orientation that (1) shows the most characteristic contour, (2)
minimizes hidden lines in the other views, (3) places the part in its
functional/manufacturing orientation, (4) puts the longest dimension
horizontally. For turned parts, axis horizontal.

## Scale

ISO 5455 recommended scales: 1:1; reduction 1:2, 1:5, 1:10, 1:20, 1:50...;
enlargement 2:1, 5:1, 10:1, 20:1... (×10 multiples). Scale AUTO must pick
from this list, never an arbitrary factor like 1:3.7.

## Sheet sizes (ISO 216 A-series, mm)

A0 1189×841 · A1 841×594 · A2 594×420 · A3 420×297 · A4 297×210 (landscape W×H).
