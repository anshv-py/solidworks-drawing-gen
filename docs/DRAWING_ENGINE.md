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

## 0. Primary rule set (default configuration)
`drawing_planner/rules/`: the owner's documents RULES (`manufacturing_drawing_rules.md`) and EX
(`manufacturing_drawing_reference_examples.md`), kept verbatim, and `drawing_rules.yaml`, which is
validated on load (`rule_set.py`) and is the only place the values below come from.

| Step | Module | Rule |
|---|---|---|
| Feature roles | `roles.py` | family SHAFT (turned, L ≥ 1.5 D) / DISC / PRISMATIC; mounting face = largest envelope face (disc: largest face ⟂ axis); bearing bore = one bore ≥ 8 mm and ≥ 1.5× the other holes, square to the mounting face (+ counterbore step); central bore = through hole on a disc axis; bearing seats / shoulders = journals ending against a larger diameter (≤ 2); clearance holes = through holes of an ISO 273 size (or an unmatched through-hole pattern, low confidence); dowel holes = ≤ 2 holes of an ISO 2338 pin size, ≥ 1 Ø deep; tapped = a thread callout exists |
| Treatments | `gdt_defaults.py` | RULES 4.1 datums (A mounting / sealing face, B bearing or central bore, C dowel hole, else envelope faces); per role (EX 7): bearing bore H7 + ⌭ 0.01 + ⊥ Ø0.02 A + Ra 0.8; central bore H8 + ⊥ Ø0.05 A; bearing seat h6 + ⌭ 0.005 + ↗ 0.02 A + Ra 0.4; shoulder ⊥ 0.02 A + Ra 1.6; clearance +0.2/0 + ⌖ Ø0.4 Ⓜ, capped at the floating-fastener limit H − F; dowel H7 + ⌖ Ø0.1; tapped ⌖ Ø0.3 Ⓜ; mounting face flatness (ISO 2768-K) + Ra 1.6. Fits are computed from the ISO 286 tables in `iso286.py` (H, JS, f, g, h, k, p up to 500 mm; others are refused, not guessed). Datums nothing references are dropped (rule 9) |
| Views | `baseline.py`, `view_rules.py` | RULES 1.1: the smallest subset of the ticked projected views (≥ 2 views always include FRONT) that still shows every dimension true size and every annotated face edge-on; one view + `THICKNESS t` note for a flat part (t ≤ 0.2 × the next envelope size). RULES 1.2: isometric only for > 3 non-orthogonal faces (fillet / chamfer faces excluded), casting / forging / moulding, or several bodies. RULES 1.3-1.6 section / auxiliary / break triggers (plan), detail triggers at the final scale (pipeline) - recorded as `view_triggers`, not drawn yet |
| Section views | `sections.py`, compiler, `hlr.py` | RULES 1.3: for a section trigger (blind hole deeper than 1.5 Ø, counterbore / countersink, coaxial stepped bores) one full section is drawn **in place of** the selected orthographic view that sees the feature axis side-on (FRONT preferred): the plane contains the axis and is parallel to that view; the solid is cut by OCCT (half-space box, `BRepAlgoAPI_Cut`), the kept half gets hidden-line removal without hidden lines, and the faces lying in the plane are hatched (ISO 128-50, ANSI31 45°). Designation `A-A` below the view; the cutting plane is shown in a selected view that sees it edge-on (added from the projected-view pool if none does) by its thick ends, arrows in the direction of sight and letters, placed beyond that view's dimensions (ISO 128-44 allows omitting the chain line between the ends). Triggers whose feature axis lies in the plane are satisfied; others stay reported. Not yet: half sections, several sections, offset / aligned sections, separate section views |
| Defaults | `baseline.py` | general tolerance ISO 2768-mK, default finish Ra 3.2 (`source=DEFAULT`) |
| CAD data | `baseline.py`, `materials.py` | title, part number, revision and material (`source=CAD_MODEL`) from `GeometryIR.cad_metadata` fill only fields the user left empty (`use_cad_metadata`, default on); weight = the file's stated mass, else exact volume × nominal density of the stated material (table in `materials.py`, printed `(CALC.)`), none if the material is unknown; each value's origin is listed in compliance item 1 |
| Gate | `drawing_qa/compliance.py` | EX 1 items 1-12 → `compliance.json`; hard blockers (1-8, 11) stamp the sheet and block `POST /api/drawings/{id}/release` |

Every inferred role carries a confidence and its reasons and is listed as an *assumed role* in the
compliance report and the UI, where the user confirms or changes it (`DrawingSettings.feature_roles`,
keyed by the deterministic GeometryIR id). `view_selection=MANUAL` restores the fixed
primary + projected views and the ISO 2768 scheme without roles.

Known limits: EX 3's common datum axis A-B of two bearing seats is drawn as datum A on the longer
seat; rule R3 (a datum feature's form tighter than every tolerance referencing it) still tightens the
mounting face below EX 4's 0.05 when a bore is ⊥ 0.02 to it; the shaft is drawn with its axis as
modelled (EX 3 asks for it horizontal); ⌭ 0.005 is reported by QA-TOL-001 as needing a CMM.

Surface finish on a hole / boss goes with its size callout (ISO 1302 symbol stacked with the frames);
planar faces keep the leader symbol. Tolerance values print with as many decimals as they need
(0.005 never becomes 0.01); QA-PMI-004 checks every frame's printed value.

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
  packing) + a leader-note column.
- Scale is the user's choice (`DrawingSettings.sheet`):
  - `scale`: the orthographic views' scale. `AUTO` (default) = the largest scale of `scale_system`
    whose layout fits. A chosen scale is used exactly: QA repairs never change it, and if the views
    do not fit, generation fails with the largest scale that does fit.
  - `scale_system`: what AUTO chooses from. `INTERMEDIATE` (default) = ISO 5455 plus the common
    intermediate steps (`DRAWING_SCALES`: … 2:1, 1.5:1, 1:1, 1:1.5, 1:2, 1:2.5, 1:3, 1:4, 1:5 …), so
    views fill the sheet; `ISO_5455` = preferred scales only. QA reports an intermediate scale as MINOR
    (QA-VIEW-004).
  - `pictorial_scale`: the isometric view's scale; `AUTO` = the rule below.
- The undimensioned pictorial (isometric) view is fixed in the sheet's **top-right corner** (below a
  revision table, if any); the orthographic grid, anchored top-left, is laid out around it. The
  corner placement wins over the view scale: AUTO picks the largest scale at which the corner is
  kept. The isometric's own scale (AUTO) is the smallest that draws it larger than every orthographic
  view (same, or one step up), else up to two steps smaller; a scale differing from the sheet is
  labelled `SCALE n:m`. Only if no scale allows the corner does it move beside the grid / to free space.
- Center marks for circles seen along their axis, centerlines for cylinders seen from the side,
  and pitch circles.
- Title block template: UNLESS OTHERWISE SPECIFIED (surface finish, linear/angular tolerance),
  FINISH, DEBURR AND BREAK SHARP EDGES (only if requested), DO NOT SCALE DRAWING, REVISION,
  NAME/SIGNATURE/DATE for DRAWN/CHK'D/APPV'D/MFG/Q.A, projection symbol, drawing type and standard,
  MATERIAL, WEIGHT, TITLE, DWG NO., sheet size, SCALE, SHEET 1 OF 1. Engineering data that was not
  supplied prints as `UNSPECIFIED`. Identification and sign-off fields stay blank.
- Values are printed with the selected decimal places *including trailing zeros* (`150.00`,
  `8X Ø8.00 THRU EQ SP`, `0.80 X 25°`), matching the references. `trailing_zeros=false` turns this off.

### Default drawing notes (on by default)
`DrawingSettings.general_notes` (`enabled=true`, `style=CONCISE`). `drawing_compiler/notes.py`
assembles the notes deterministically.

**CONCISE (default)**, modelled on an external reference drawing generator (not part of this repository): standard,
units, projection, "DO NOT SCALE DRAWING"; the general tolerance; the datum reference frame (when
datums exist); the TED statement (when boxed dimensions exist); then only the optional items the user
supplied (surface finish, edge break, own notes). Nothing is printed as a placeholder unless the
general tolerance itself is missing (default GD&T off and none supplied).

**FULL** (`style=FULL`), the complete manufacturing checklist, in this fixed order:
1. Standard, units, projection and "DO NOT SCALE DRAWING".
2. General linear (and angular) tolerance.
3. General geometric tolerance.
4. Datum reference frame, naming each datum's real feature from GeometryIR (e.g.
   `A = PLANAR FACE -Z (Z = 0.00); B = Ø45.00 BOSS AXIS`).
5. Envelope statement (ASME Rule #1; datum features of size at RMB unless MMB/LMB is shown) or
   independency statement (ISO 8015).
6. Datum feature form refinement, with the limit it must be tighter than.
7. Surface finish default plus a pointer to the specific symbols.
8. Deburr / edge break.
9. Material, and "NO SUBSTITUTION WITHOUT WRITTEN APPROVAL".
10. Heat treatment, coating and masked surfaces.
11. Thread class.
12. Process and machining vs HT/coating sequence.
13. Drawing governs the 3D model (file name and revision).
14. Inspection / documentation.
15. Marking / traceability.

The user's own notes follow as 16, 17, … Then come "WHAT THE SUPPLIER MUST NOT ASSUME" (4 bullets)
and a one-line summary of the controlling standard and default tolerances.

Rules for the notes:
- Every value comes from the user's settings or from GeometryIR. Anything missing prints as a
  `[PLACEHOLDER]`, and QA-NOTE-001 lists the placeholders.
- User values print exactly as entered.
- Text is 2.5 mm. The block is one 180 mm column above the title block (as in the references), a
  two-column band above it, or one wide column along the bottom edge left of the title block (frees
  the height on the right for the views). The compiler picks the arrangement that keeps the
  isometric in its corner at the larger view scale; ties go to the single column.
- If the notes cannot fit (e.g. a crowded A4), layout fails with a message that says so. The
  notes are never shrunk below 2.5 mm or dropped.
- A pictorial view that does not fit in the projection grid floats to free space. It may drop one
  ISO scale step, and is then labelled `SCALE 1:n`.

### Datum-scheme rules (`drawing_planner/datum_rules.py`)
- **Checked by QA (reported, never auto-corrected):**
  - R3: every referenced datum feature has its own form control (flatness / cylindricity),
    tighter than every tolerance referencing it.
  - R7: no sheet-edge datums for sheet metal. Machined features or datum targets are required
    for cast, forged, welded and moulded parts.
  - R8: one datum per feature, and no self-referencing frames.
  - R9: every datum on the drawing is referenced.
  - A tolerance zone below 0.01 mm is flagged as not verifiable with standard shop equipment.
- R3 accepts an orientation tolerance to other datums (e.g. B ⊥ A) as the datum feature's own
  control, since an orientation zone also limits form (ISO 1101 / ASME Y14.5).
- **Default scheme, applied directly** (`drawing_planner/gdt_defaults.py`, see below).
- **Suggestion API (no longer shown in the UI):** `suggest_datums`, rules 1, 2, 4, 5 and 7.
  - Primary: a continuous planar face perpendicular to the part's axes, with area only as a
    tie-breaker. A long turned part uses its journal axis instead.
  - Secondary: the pilot boss on the main axis before a bore, and a bore before the outer diameter.
  - Tertiary: an off-axis hole for clocking, or a perpendicular face.
  - Sheet metal: a face plus two holes.
  - The suggestion carries its reasons and cautions (function, probe and clamp access, machined
    features), because geometry cannot reveal them.
- In ASME mode the UI labels datum modifiers RMB/MMB/LMB (ASME Y14.5-2018 terms).

### Default datums and GD&T (`drawing_planner/gdt_defaults.py`, on by default)
Applied by the planner when the user supplied **no** datums or feature control frames
(`DrawingSettings.default_gdt=true`; entering any datum/frame, or setting it false, disables it).
Conventions follow an external reference drawing generator (datum corner = bounding-box minimum faces,
from which the hole locations are dimensioned). Every value is derived from the declared general
tolerance **ISO 2768-mK**, which is written to `engineering_information.general_tolerance` with
`source=DEFAULT` (never `USER`) unless the user supplied a tolerance.

| Part family | Datums | Frames |
|---|---|---|
| Prismatic, with holes | A/B/C = the three bounding-box minimum faces, largest area first | A flatness; B ⊥ A; C ⊥ A\|B; each hole callout ⌖ Ø t \|A\|B\|C\| |
| Prismatic, no holes | A = largest bounding-box minimum face | A flatness; opposite face ∥ A |
| Disc / flange (length < 1.5 D) | A = largest face ⟂ axis; B = main-diameter axis (only if there are holes to locate) | A flatness; main Ø ⊥ A (Ø zone); hole callouts ⌖ Ø t \|A\|B\| |
| Shaft (length ≥ 1.5 D) | A = axis of the longest journal | A straightness (Ø zone); other journals and the largest shoulder ↗ 0.2 \|A\| |

Values: flatness/straightness and perpendicularity from the ISO 2768-2 class K tables (nominal
length = the feature's largest in-plane extent), circular run-out 0.2 (class K). Position: the Ø zone
circumscribing the ±t square of ISO 2768-1 class m for the largest locating distance
(Ø 2·√2·t, rounded down to 0.05). The hole-locating dimensions (and PCD) become boxed TEDs
(`manufacturing.basic_dimensions`). Rule R3 is met by construction: a datum feature's own control is
capped one preferred step below every tolerance that references it.

Only targets the drawing can show are used (placed callouts / diameter dimensions, faces edge-on in a
selected view). With scale AUTO, if the annotations do not fit the selected sheet at any scale, the
pipeline re-plans without them and records a plan uncertainty. With a scale the user chose they are
never dropped: the drawing fits, or generation fails naming the largest scale that fits.

### Manufacturing annotations (user-supplied)
`DrawingSettings.manufacturing` (schema: `drawing_schema/pmi.py`) carries datums, GD&T feature
control frames, dimension tolerances (±, deviation, limits), thread callouts, inspection
dimensions, basic (TED) dimensions, ISO 1302 surface finish marks, feature notes, sheet notes and
revisions. Apart from the default datum/GD&T scheme above (labelled, switchable), **none of it is
generated.** Every item references a GeometryIR face/feature or a placed dimension.
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
