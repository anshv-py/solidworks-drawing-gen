# Drawing engine (implemented - milestone 2)

```
GeometryIR ──► candidate engine ──► planner (rules) ──► DrawingPlan ──► compiler ──► CompiledDrawing
  (OCCT)       (values from IR)     view choice,         (ids only,      layout, ISO     (sheet ops,
                                    redundancy           no values)      5455 scale,     executor-neutral)
                                                                         placement
CompiledDrawing ──► executor ──► DXF ──► PDF / SVG / PNG ──► QA ──► repair loop (≤ 3) ──► export
                    OCCT HLR +          ezdxf drawing add-on     deterministic   CRITICAL blocks export
                    ezdxf               + matplotlib
```

Everything runs in a subprocess (`python -m drawing_executor generate`) started by the API job
runner. **No LLM is used.** SolidWorks is not required.

## Why no LLM
Choosing views, dimensions, redundancy and layout can be done completely with drafting rules.
Rules are reproducible, testable and cannot invent values, and the project principles require
deterministic implementations where they exist. The open-weight "frontier" models that were
considered cost a lot to run:

| Model | Weights | Licence | Serving cost |
|---|---|---|---|
| DeepSeek-V4-Pro | 1.6T MoE, 49B active, ~865 GB | MIT | multi-GPU (≈8× B200 or 16+ H100) |
| Kimi K3 | 2.8T MoE, 104B active | custom Kimi K3 licence (revenue-gated) | larger still |
| Qwen3.8 Max-class (2.4T-A95B) | open weights | custom licence (revenue-gated); hosted API is paid | multi-GPU |

(Figures from web search on 2026-09-24, not verified against the model cards.) None of these is
"free" to run, and none is needed. An LLM hook remains configurable (`CADAI_LLM_BACKEND`, default
`none`) for future assistance such as explaining QA findings. It must never supply values.

## 1. Dimension candidates (`services/drawing-planner/candidates.py`)
Each candidate copies its value from a named GeometryIR field (`source`):

| Candidate | From | Rule |
|---|---|---|
| Overall X/Y/Z | `bounding_box.size` | skipped for an axis a boss Ø spans completely (turned parts) |
| Hole callout `nX Ø.. THRU / DEPTH`, `CBORE`, `CSK`, `EQ SP` | hole features, patterns | identical holes are grouped; pattern members share one callout |
| PCD | circular pattern | shown on a centre-line pitch circle |
| Hole / pattern location | hole centre − `bounding_box.min` | baseline from the part's min faces; skipped for holes on a boss axis and for patterns centred on another feature |
| Pattern pitch `n-1X p` | pattern pitches | reference member + pitch |
| Boss Ø, step length | boss diameter/height (+ axial legs of end chamfers) | a shaft step is measured to the end face |
| Pocket L/W/depth + location, slot L/W + location | pocket / slot features | |
| `nX R..` | cylindrical fillets | identical radii grouped |
| `nX d × 45°` | chamfers | planar or conical |

## 2. Planner (`baseline.py`)
- Filters categories by the user's dimension preferences.
- **Redundancy:** linear dimensions are intervals on a model axis. A union-find over the end
  points drops any dimension that would close a chain or duplicate an interval. Face/edge points
  link only with faces, and feature centres only with centres, so a hole centre that merely
  shares a coordinate with a slot end is not treated as a chain.
- **View assignment:** a candidate goes to a selected orthographic view that shows it true
  size. Hole callouts prefer the view that looks at the hole's open side. Pockets and slots
  prefer the view that looks into their opening. Locations and sizes follow their feature's view.
- **Model up axis** (`view_frame`): `Z_UP` (front looks along +Y) or `Y_UP` (the SolidWorks
  frame: front looks along −Z). The file's own coordinates are never changed.

## 3. Compiler (`services/drawing-compiler`)
- Sheet format modelled on the SolidWorks standard templates: 10 mm margins with an ISO 5457
  zone grid (A4 6×4, A3 8×6, A2 12×8, A1 16×12, A0 24×16; columns numbered right to left,
  rows lettered bottom to top). A 180 × 55 mm title block sits bottom-right, a numbered
  `Note:` block directly above it, and a revision table top-right (only when revisions are
  supplied). All three are obstacles for the view layout.
- Views are placed on a grid by projection method. First angle: TOP below FRONT, RIGHT to its
  left. Third angle is mirrored. Aligned views share projection lines.
- Each view envelope = outline + dimension tiers (shorter dimensions inside, greedy interval
  packing) + a leader-note column. The chosen scale is the largest ISO 5455 scale whose layout fits.
- Center marks for circles seen along their axis, centerlines for cylinders seen from the side,
  and pitch circles.
- Title block template: UNLESS OTHERWISE SPECIFIED (surface finish, linear/angular tolerance),
  FINISH, DEBURR AND BREAK SHARP EDGES (only if requested), DO NOT SCALE DRAWING, REVISION,
  NAME/SIGNATURE/DATE for DRAWN/CHK'D/APPV'D/MFG/Q.A, projection symbol, drawing type and standard,
  MATERIAL, WEIGHT, TITLE, DWG NO., sheet size, SCALE, SHEET 1 OF 1. Engineering data that was not
  supplied prints as `UNSPECIFIED`. Identification and sign-off fields stay blank.
- Values are printed with the selected decimal places *including trailing zeros* (`150.00`,
  `8X Ø8.00 THRU EQ SP`, `0.80 X 25°`), matching the references. `trailing_zeros=false` turns this off.

### Manufacturing annotations (user-supplied only)
`DrawingSettings.manufacturing` (schema: `drawing_schema/pmi.py`) carries datums, GD&T feature
control frames, dimension tolerances (±, deviation, limits), thread callouts, inspection
dimensions, ISO 1302 surface finish marks, feature notes, sheet notes and revisions. **None of
it is ever generated.** Every item references a GeometryIR face/feature or a placed dimension.
The checks run in this order:
1. Schema grammar. Form tolerances take no datum. Orientation/runout tolerances need one. A
   Ø zone and MMC/LMC only apply to characteristics that allow them. Frames may only
   reference datums that are defined. Datum letters exclude I, O and Q.
2. The planner (`pmi_validation.py`) checks the targets:
   - Every target exists.
   - Datum and finish faces are planar.
   - MMC applies only to size features.
   - Flatness applies only to a planar face.
   - Tolerances refer to dimensions that are on the drawing.
   - A thread goes on a hole, its nominal size is ≥ the hole Ø, and a blind hole's thread
     depth is ≤ the hole depth.

   Errors → API 422 `PMI_INVALID` (and job error `PMI_INVALID`).
3. The compiler places each item deterministically:
   - **Hole / pattern:** the frame goes under the hole callout; a datum hangs below it.
   - **Boss:** at its Ø dimension. The datum triangle sits on the dimension line, clear of the frame.
   - **Planar face:** in the orthographic view that shows it edge-on, on a leader outside the
     dimension tiers. The leader foot is moved along the face, and the box sideways with an
     angled leader, until no leader or box crosses dimension text, frames or other annotations.
   - Anything that cannot be placed is recorded (`UNPLACED` / `CROWDED`) and reported by QA.
     It is never dropped silently.

## 4. Executor (`services/drawing-executor`)
- **OCCT `HLRBRep_Algo`** (exact hidden-line removal) per view: visible edges and silhouettes,
  plus hidden edges when "hidden lines shown" is selected. Smooth tangent edges are omitted.
- Extension lines are snapped to the first drawn edge between the feature and the dimension line.
  Feature centres keep their own extension lines.
- DXF R2018 in mm (ezdxf, MIT). Layers: VISIBLE 0.5, HIDDEN (dashed) 0.25, CENTER (centre line)
  0.18, DIM 0.18, and TITLE/FRAME. Linear dimensions are real `DIMENSION` entities whose text is the
  GeometryIR value. Leaders have filled arrows.
- PDF/SVG/PNG are rendered from the DXF at true sheet size (A3 = 420 × 297 mm, verified by test).
- Arrowheads are closed and filled (ISO 129-1). Text uses an Arial-metric sans (Liberation Sans;
  ezdxf falls back to another installed font if it is missing).
- GD&T is drawn as vector graphics:
  - Characteristic symbols for all 14 ISO 1101 / ASME Y14.5 characteristics.
  - Ø zones and circled Ⓜ/Ⓛ modifiers.
  - Datum feature symbols: filled triangle, line and boxed letter.
  - Stacked deviation / limit tolerances, and inspection ovals.
  - ISO 1302 basic surface-texture symbols with Ra (no process requirement is implied).
  - The ISO 128 first/third-angle projection symbol.
- The isometric view is **shaded with edges**: OCCT triangulation, flat Lambert shading,
  back-face culling, painter's order, with the exact HLR edges drawn on top. It is display only
  and never used for measurement.
- A toleranced or inspection dimension is still a `DIMENSION` entity (its own text suppressed)
  plus explicit text entities for the value and tolerance.
- Provenance (*"Generated by CAD Drawing AI (open-source OCCT HLR + ezdxf). Not produced by
  SolidWorks."*, executor versions, date) is printed small inside the title block, not in
  the drawing area.

## Formats
| Format | Status |
|---|---|
| PDF, DXF, SVG, PNG preview | ✅ open-source executor |
| DWG | ⛔ needs the SolidWorks worker. There is no free, licence-compatible DWG writer (LibreDWG is GPL; ODA is commercial). The API returns 501 `FORMAT_REQUIRES_SOLIDWORKS` |
| SLDDRW | ⛔ needs the SolidWorks worker (501) |

## Known limitations
- No section or detail views yet: internal features are shown with hidden lines.
- Projection symbol proportions are approximate. Its orientation was derived from the
  first/third-angle definition and has not been checked against the ISO 5456-2 text.
- Leader notes sit in a column to the right of each view, so hole-callout leaders can cross part geometry.
- Not implemented: sheet-metal (bend tables, flat patterns), weld symbols, BOM/balloons (single
  parts only), GD&T on angular dimensions, composite frames, datum targets, multi-sheet drawings.
- Only axis-aligned features get location dimensions. Torus fillets are not dimensioned.
- STL models cannot be drawn: there are no exact edges for hidden-line removal.
