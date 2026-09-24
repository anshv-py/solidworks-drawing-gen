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
- ISO 5457 frame (20 mm filing margin), with a 40 mm strip reserved for the title block and notes.
- Views are placed on a grid by projection method. First angle: TOP below FRONT, RIGHT to its
  left. Third angle is mirrored. Aligned views share projection lines.
- Each view envelope = outline + dimension tiers (shorter dimensions inside, greedy interval
  packing) + a leader-note column. The chosen scale is the largest ISO 5455 scale whose layout fits.
- Center marks for circles seen along their axis, centerlines for cylinders seen from the side,
  and pitch circles.
- Title block (16 fields) with material, general tolerance and finish = `UNSPECIFIED` unless
  supplied with a source.

## 4. Executor (`services/drawing-executor`)
- **OCCT `HLRBRep_Algo`** (exact hidden-line removal) per view: visible edges and silhouettes,
  plus hidden edges when "hidden lines shown" is selected. Smooth tangent edges are omitted.
- Extension lines are snapped to the first drawn edge between the feature and the dimension line.
  Feature centres keep their own extension lines.
- DXF R2018 in mm (ezdxf, MIT). Layers: VISIBLE 0.5, HIDDEN (dashed) 0.25, CENTER (centre line)
  0.18, DIM 0.18, and TITLE/FRAME. Linear dimensions are real `DIMENSION` entities whose text is the
  GeometryIR value. Leaders have filled arrows.
- PDF/SVG/PNG are rendered from the DXF at true sheet size (A3 = 420 × 297 mm, verified by test).
- Every sheet states: *"Generated by CAD Drawing AI - open-source OCCT/ezdxf executor. Not
  produced by SolidWorks."*

## Formats
| Format | Status |
|---|---|
| PDF, DXF, SVG, PNG preview | ✅ open-source executor |
| DWG | ⛔ needs the SolidWorks worker. There is no free, licence-compatible DWG writer (LibreDWG is GPL; ODA is commercial). The API returns 501 `FORMAT_REQUIRES_SOLIDWORKS` |
| SLDDRW | ⛔ needs the SolidWorks worker (501) |

## Known limitations
- No section or detail views yet: internal features are shown with hidden lines.
- The ISO 5456-2 projection *symbol* is not drawn (the method is stated in the title block) until
  the symbol geometry has been checked against the standard.
- Leader notes sit in a column to the right of each view, so leaders can cross part geometry.
- Only axis-aligned features get location dimensions. Torus fillets are not dimensioned.
- STL models cannot be drawn: there are no exact edges for hidden-line removal.
