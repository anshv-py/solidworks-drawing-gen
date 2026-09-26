# Manufacturing Drawing Generation Rules
### Decision logic for a SolidWorks-to-manufacturing-drawing converter (view selection, dimensioning, GD&T)

This file is written as a **rule engine**, not a narrative reference. Each section
gives: (a) the trigger condition (what about the part/feature causes the rule to
fire), (b) the action (what the drawing must contain), and (c) the reasoning
(why, tied to ASME Y14.5 / ISO GPS conventions), so an agent can pattern-match
features → rules → drawing output instead of "understanding" a textbook.

Use this as a system/knowledge document for the drawing-generation tool. Where
useful, rules are also given as pseudocode / YAML so they can be parsed
programmatically instead of only read as prose.

---

## 1. View Selection Logic

### 1.1 Default: Orthographic multiview (First/Third angle)
- **Trigger:** every part, always. This is the baseline — isometric is a
  *supplement*, never a replacement, for dimensioned production drawings.
- **Action:** generate the minimum number of orthographic views that fully
  define the part with no ambiguity — typically front, top, right (3rd angle,
  US) or front, top, left (1st angle, ISO/most of world outside US). Determine
  projection system from a project setting; label the projection symbol
  (cone/truncated-cone ISO symbol) on the drawing.
- **View count logic:**
  - 1 view sufficient → only for parts fully defined by one view + a note
    (e.g., a flat gasket/shim: outline view + "THICKNESS X mm" note; a shaft
    with only diameters: one view + diameter callouts using ⌀ prefix removes
    need for a circular end view).
  - 2 views → axisymmetric parts with features only in one non-rotational
    direction (most turned parts: front + one end view for keyway/flat/hole).
  - 3 views → default for prismatic / machined block-type parts.
  - >3 views → only when features on faces can't be shown without a 4th view
    (e.g., a feature on the back face not inferable by symmetry) — prefer a
    section or auxiliary view over adding a full extra orthographic view if
    only one feature needs to be shown.

### 1.2 When an isometric (or other pictorial) view IS required
Add an isometric/trimetric pictorial view (non-dimensioned, for clarity only)
when **any** of the following triggers fire:
| Trigger | Reason |
|---|---|
| Part has ≥4 machined faces with non-obvious spatial relationship (e.g., angled bosses, ribs, non-planar faces) | Orthographic views alone force the reader to mentally reconstruct 3D shape; isometric removes ambiguity |
| Part is a casting/forging/molded part with draft, ribs, or bosses | Complex organic-looking geometry reads poorly in 2D-only views |
| Sheet-metal part with multiple bends (>2 bend lines) | Bend direction/sequence is easier to convey pictorially before the flat pattern |
| Assembly or sub-assembly drawing | Isometric (often exploded) view is expected/standard for assemblies regardless of part complexity |
| First-time / non-standard part shape (not a simple prismatic/turned form) | Reduces misreads by shop floor operators |
| Drawing will be used for manual/CNC setup instruction, not just machinist reference | Pictorial views speed up operator comprehension |
- **Action when NOT dimensioned:** isometric view gets no dimensions, no
  tolerances — it is for visualization only, placed top-right or in a
  dedicated cell, and shaded/shaded-edges optional.
- **Do NOT** add isometric for simple prismatic blocks, simple turned shafts,
  simple flat plates, or standard fasteners — it adds drawing clutter with no
  benefit. Isometric is a supplement for genuine spatial-comprehension
  difficulty, not a default per-drawing item.

### 1.3 Section views — triggers
Add a section view when:
- An internal feature (bore, counterbore, internal thread, internal groove,
  hidden cavity) **cannot be dimensioned clearly with hidden lines** in a
  standard view. Rule of thumb: if a feature needs >2 hidden-line dimension
  callouts stacked on the same view, convert to a section.
- Any part with a blind or through hole deeper than it is wide (aspect ratio
  >1.5:1) where wall thickness or depth must be toleranced.
- Symmetric parts revolved about a single axis → use a **half section**
  (one half external view, one half sectioned) instead of a full section.
- Concentric/stepped bores (e.g., counterbore + through-hole + chamfer stack)
  → **full section** required, hidden lines are not an acceptable substitute.
- **Hatching rule:** 45° section lines, alternate angle/spacing for adjacent
  parts in an assembly section; ribs, webs, and thin walls are NOT hatched
  when the cutting plane runs along their length (standard convention to
  avoid implying solid mass).
- **Cutting plane line + section letters (A-A, B-B…)** always shown on the
  view being sectioned, arrows indicating direction of sight.

### 1.4 Detail views — triggers
Add a detail view (circled callout, enlarged elsewhere on the sheet, scale
labeled e.g. "SCALE 2:1" or "DETAIL A") when:
- A feature's dimensions/tolerances cannot be legibly placed at the drawing's
  main scale (small holes, small grooves, knurls, small fillets/chamfers on
  an otherwise large part).
- Any feature has GD&T tolerance values tighter than ±0.05 mm (or equivalent)
  on a part drawn smaller than ~1:2 scale — always detail it.
- Repeated small features (e.g., one of an array of identical small slots) —
  detail one instance and note "TYP" (typical) rather than clutter every
  instance.
- **Never** use a detail view as a substitute for a section view when the
  feature is internal — details enlarge, sections reveal internal geometry;
  use both together if a small internal feature needs both effects.

### 1.5 Auxiliary views — triggers
Add an auxiliary view when a surface is **not parallel to any of the three
principal projection planes** (an angled face), and that surface carries:
- A feature that must be shown true-size/true-shape (a hole normal to the
  angled face, a slot, a chamfer edge length) — an auxiliary view projected
  perpendicular to that face is required; without it, the feature appears
  foreshortened and cannot be correctly dimensioned.
- If the angled face carries no dimensioned feature (pure stylistic angle,
  no holes/slots on it), an auxiliary view is optional — a note in the
  orthographic views may suffice.

### 1.6 Broken-out / partial views & break lines
- **Trigger:** long uniform-section parts (shafts, extrusions, tubes) where
  showing full length at a legible scale would make the sheet impractically
  long, AND the full length is captured elsewhere by an overall length
  dimension.
- **Action:** insert a conventional break (zig-zag or "S" break line for
  cylindrical parts), remove the redundant middle, dimension overall length
  across the break.

### 1.7 View-selection decision flow (pseudocode)
```
for each part:
    views = generate_min_orthographic_views(part)          # 1.1
    if is_complex_or_organic_shape(part) or is_assembly(part):
        add_isometric(dimensioned=False)                    # 1.2
    for feature in part.features:
        if feature.is_internal and not clearly_dimensionable_in(views):
            add_section_view(cutting_plane=best_plane(feature))   # 1.3
        if feature.tolerance < TIGHT_TOL_THRESHOLD or feature.size < SMALL_FEATURE_THRESHOLD:
            add_detail_view(feature, scale=auto_scale(feature))    # 1.4
        if feature.face_normal not in {X, Y, Z}:
            add_auxiliary_view(feature.face)                       # 1.5
    if part.uniform_section_length / part.diameter_or_width > BREAK_RATIO:
        apply_conventional_break(views)                            # 1.6
```

---

## 2. Dimensioning Rules

### 2.1 General principles
- Dimension **features**, not derived geometry — never dimension to an
  edge created only by a section cut or a hidden intersection.
- Every dimension appears **once** on the drawing (no duplicate dimensions
  across views — pick the view where the feature is true-size/true-shape).
- Dimension from **finished/functional datums** outward, not from
  arbitrary corners, unless the corner IS the functional datum.
- Do not dimension inside the outline of the part where avoidable; keep
  dimension lines outside the view, nested smallest-to-largest outward.
- Units: one unit system per drawing (mm default unless project specifies
  inch); do not mix.

### 2.2 Dimension type selection
| Feature | Dimension type |
|---|---|
| Hole (through or blind) | Diameter (⌀) + depth if blind; call out THRU if through |
| Shaft/boss (cylindrical, external) | Diameter (⌀) |
| Fillet / round | Radius (R) |
| Chamfer (45°) | "C" value (e.g., C1.5) or angle+linear (1 x 45°) |
| Chamfer (non-45°) | Angle + linear dimension, not the C shorthand |
| Counterbore | ⌀ + depth, called out as "⌀X ⊔ ⌀Y ▽Z" per ASME symbol stack |
| Countersink | ⌀ + included angle, "⌀X ⌵ Yy°" |
| Thread | Designation per standard (e.g., M8x1.25-6H) — never dimension thread by diameter+pitch separately if a standard designation exists |
| Slot | Width + length (or width + center-to-center + end radius) |
| Angle | Angular dimension, always to a defined datum edge/axis |
| Pattern of identical holes | One dimensioned instance + "X PLACES" / bolt-circle + angular spacing |

### 2.3 Baseline vs chain vs coordinate dimensioning
- **Baseline (datum) dimensioning** — default for features whose location
  tolerance stacks would otherwise accumulate (mating parts, hole patterns
  relative to a locating edge). Use when tolerance accumulation matters
  functionally.
- **Chain dimensioning** — acceptable only for non-critical, sequential
  features (e.g., decorative grooves) where accumulated tolerance is
  functionally irrelevant. Avoid by default on functional/mating features.
- **Coordinate (tabular) dimensioning** — trigger: >6 holes of the same
  size at irregular positions (e.g., PCB-style mounting patterns). Use an
  X/Y table referenced to two datum edges instead of cluttering the view
  with dimension lines.

### 2.4 Placement rules
- Dimension lines: minimum 10 mm from the outline, 6 mm between parallel
  dimension lines (scale these visually, not literally, per sheet size).
- Extension lines: small gap from the part outline, slight overrun past
  the dimension line.
- Leaders for notes/GD&T point to the feature, not to another dimension
  line.

---

## 3. Tolerancing

### 3.1 General (unstated) tolerances
- **Trigger:** any dimension without an explicit tolerance.
- **Action:** apply a general tolerance block per ISO 2768 (or the
  project's standard, e.g., ASME Y14.5 default tol. block) sized to the
  process class (fine/medium/coarse) declared once in the title block —
  do not repeat on every dimension.
- Use general tolerance for non-functional/non-mating dimensions only.

### 3.2 Explicit tolerances — when required
Apply an explicit ± or limit tolerance (overriding the general block) when
the feature is:
- A mating/fit dimension (shaft into bore, pin into hole, bearing seat).
- Load-bearing or safety-critical.
- Called out in the CAD model with a tolerance already assigned (pass
  through directly — do not default to general tolerance if the model
  specifies one).

### 3.3 Limits & fits (ISO 286) — hole/shaft basis logic
```
if fit_type == "clearance":
    prefer Hole-basis: Hole = H7 (default), Shaft = f7/g6 depending on
    clearance amount needed (running/sliding fit tables)
elif fit_type == "transition":
    Hole = H7, Shaft = k6/j6
elif fit_type == "interference":
    Hole = H7, Shaft = p6/s6 (press fit) — verify with stress/assembly force calc
```
- Default to **hole-basis system** unless the project explicitly uses a
  standard shaft (e.g., off-the-shelf shafting) — then switch to
  shaft-basis.
- Always state fit class next to BOTH mating dimensions on their
  respective part drawings (e.g., ⌀20 H7 on the housing, ⌀20 g6 on the
  shaft) so each drawing is independently manufacturable.

---

## 4. GD&T Logic (Feature Control Frame Decision Tree)

This is the core logic for making drawings "manufacturing ready" rather
than just dimensioned.

### 4.1 Datum selection — do this BEFORE assigning any GD&T symbol
1. Identify the part's **functional datums**: the surfaces/axes/points
   that locate the part in its assembly or on a fixture (mounting face,
   locating bore, locating pins).
2. Assign datum letters (A, B, C…) in order of constraint priority:
   - **Datum A** = primary — usually the largest flat mounting face or the
     axis of the primary locating bore. Removes most degrees of freedom
     (3: rejects rotation about 2 axes + translation along 1).
   - **Datum B** = secondary — locates 2 more DOF (typically a
     perpendicular face or a second hole).
   - **Datum C** = tertiary — locates final rotational DOF (e.g., a
     keyway, slot, or off-axis hole).
3. **Never** assign a datum to a non-functional/cosmetic surface just
   because it's convenient to measure from.

### 4.2 Symbol selection decision tree
```
IF feature is a single flat surface, tolerance is on the surface ITSELF
   with no reference to other features:
     → FLATNESS (⏥)              [form tolerance, no datum needed]

IF feature is a single axis/line-element, tolerance is on straightness of
   that line/axis alone:
     → STRAIGHTNESS (—)          [form tolerance, no datum needed]

IF feature is a circular cross-section, tolerance controls roundness:
     → CIRCULARITY / ROUNDNESS (○)   [form, no datum]

IF feature is a cylindrical surface, tolerance controls combined
   roundness + straightness along the cylinder:
     → CYLINDRICITY (⌭)          [form, no datum]

IF feature (surface or axis) must be tolerant to a REFERENCE datum plane,
   and the required relationship is:
     - 90° to datum          → PERPENDICULARITY (⊥)   [needs datum]
     - parallel to datum      → PARALLELISM (∥)         [needs datum]
     - fixed angle ≠ 90°      → ANGULARITY (∠)          [needs datum]

IF feature is the LOCATION of a hole, boss, slot, or pattern relative to
   datum(s):
     → POSITION (⊕)             [needs datum(s); this is the single most
                                  common GD&T callout for manufacturing —
                                  replaces ± location dimensioning]

IF feature is a hole/shaft whose axis must be coincident/coaxial with
   another feature's axis:
     → CONCENTRICITY (◎) if axis-to-axis (RARE — position is usually
        preferred; concentricity is hard to inspect, avoid unless the
        design explicitly needs derived-median-line control)
     → COAXIALITY via POSITION (⊕) at MMC — PREFERRED modern practice

IF feature must be symmetric about a datum plane/axis (matching a mirror
   feature on the opposite side):
     → SYMMETRY (⌯) — RARE, usually replaced with POSITION in modern
        practice for the same inspection reason as concentricity above

IF feature is a surface of revolution (shaft, bore) and its total
   run-out around the axis matters (combined form+location+orientation
   as seen from one direction while rotating about datum axis):
     → CIRCULAR RUNOUT (↗) if checked at individual cross-sections
     → TOTAL RUNOUT (↗↗) if checked along the entire surface at once

IF feature is a complex/free-form surface (not a plane, cylinder, or
   simple curve) and its shape (not just size) must be controlled:
     → PROFILE OF A SURFACE (⌓) [can be applied with or without datums;
        with datums it also controls location/orientation — the single
        most versatile GD&T callout, default choice for cast/formed
        surfaces and surfaces that don't fit the other categories]

IF feature is a single line-element of a surface (not the whole surface):
     → PROFILE OF A LINE (⌒)
```

### 4.3 Material condition modifiers — when to apply
| Modifier | Symbol | Apply when |
|---|---|---|
| Maximum Material Condition | Ⓜ | Feature is size-variable (hole/shaft) AND a functional (assembly-clearance) reason exists to allow more position tolerance as the feature departs from MMC — i.e., bonus tolerance is functionally acceptable. Default choice for most position callouts on clearance holes. |
| Least Material Condition | Ⓛ | Wall-thickness / minimum-edge-distance is the functional concern (avoid breakout, ensure minimum wall) rather than assembly clearance. |
| Regardless of Feature Size | (no symbol, default) | Feature is not size-variable, or a fixed/consistent tolerance is required regardless of the produced size (common for precision/critical features, bearing bores, sealing surfaces). |
- **Default rule:** if unsure, use RFS (no modifier) for functional/sealing
  features and MMC for simple clearance-hole bolt patterns — this mirrors
  the vast majority of real drawings and gives the most bonus tolerance
  where it's safe to do so.

### 4.4 Typical callouts by feature type (ready-to-apply defaults)
| Feature | Default GD&T callout |
|---|---|
| Primary mounting face | Flatness (no datum) + serves as Datum A |
| Bolt-hole pattern (clearance) | Position ⊕ Ø-tolerance Ⓜ, referenced A\|B\|C |
| Locating/dowel hole (tight fit) | Position ⊕ Ø-tolerance (RFS), referenced A\|B |
| Bearing bore | Cylindricity + Position (RFS), Perpendicularity to shoulder face |
| Shaft seat for bearing | Cylindricity + Circular runout to datum axis |
| Sealing face (O-ring gland, gasket face) | Flatness + Surface finish callout (see §5) |
| Keyway/slot | Position ⊕ (symmetric callout) referenced to shaft axis datum |
| Cast/molded outer surface | Profile of a surface ⌓, unilateral or bilateral per draft requirements |
| Threaded hole | Position ⊕ at MMC on the pitch diameter (per ASME Y14.5 thread rules), no separate size tolerance beyond thread class |

### 4.5 Feature control frame construction rule
```
[Symbol | Tolerance value (Ⓜ/Ⓛ if applicable) | Datum1 | Datum2 | Datum3]
```
- List datums in precedence order left to right.
- Compound/two-tier feature control frames (composite position tolerancing)
  trigger when a pattern has BOTH a pattern-locating tolerance (looser,
  referencing all datums) AND a feature-to-feature tolerance within the
  pattern (tighter, fewer/no datums) — use composite tolerancing instead of
  inventing two separate single-segment callouts.

---

## 5. Surface Finish Specification

| Surface function | Typical Ra (µm) | When to call out |
|---|---|---|
| As-cast / as-molded, non-functional | 12.5–25 | No explicit callout — general note "AS CAST" sufficient |
| General machined surface, non-mating | 3.2–6.3 | Basic ✓ symbol, value only |
| Mating/bearing surface | 0.8–1.6 | ✓ symbol + value, apply to the specific surface not the whole part |
| Sealing surface (O-ring, gasket) | 0.4–0.8 | ✓ symbol + value + note "no circumferential lay" if relevant |
| High-precision bearing/sliding surface | 0.1–0.4 | ✓ symbol + value + lay direction symbol if directional finish required |
- Apply finish symbols to the **specific surface(s)** via leader, or as a
  general note + "EXCEPT AS NOTED" with local overrides — never apply a
  single blanket finish value silently to functional and non-functional
  surfaces alike.
- If a machining process is mandated (grinding, honing, lapping) rather
  than just a finish value, state the process in a note near the callout.

---

## 6. Manufacturing-Readiness Checklist (run before releasing a drawing)

1. ☐ Title block complete: material, general tolerance standard, finish
   default, projection angle symbol, drawing number/revision, scale.
2. ☐ Every dimension traceable to a functional datum or general tolerance —
   no "floating" undimensioned features.
3. ☐ No duplicate/redundant dimensions across views.
4. ☐ Every toleranced mating feature has an explicit fit class or GD&T
   callout — nothing critical left to the general tolerance block.
5. ☐ Datum reference frame (A, B, C) established and consistent across all
   GD&T callouts on the part.
6. ☐ All threads called out with full standard designation + depth
   (and thread relief/chamfer if required).
7. ☐ Section views used wherever hidden lines would otherwise stack on
   internal features.
8. ☐ Isometric included only where genuinely needed for clarity (§1.2).
9. ☐ Surface finish specified on all functional surfaces; general note
   covers the rest.
10. ☐ Bill of material / part number / rev letter present for assemblies.
11. ☐ Break lines applied to any view that would otherwise force an
    impractically small scale.
12. ☐ Units and tolerance standard consistent across the whole sheet.

---

## 7. Suggested Rule Schema (for programmatic consumption)

If the tool benefits from structured rules rather than parsing this
markdown as prose, the same logic can be expressed as data. Example
(YAML) — extend per feature type as the tool's feature-recognition
improves:

```yaml
view_rules:
  - trigger: "feature.type == 'internal_bore' and hidden_line_count > 2"
    action: "add_section_view"
  - trigger: "feature.tolerance_value < 0.05 or feature.size < 3mm"
    action: "add_detail_view"
  - trigger: "face.normal not in [X,Y,Z]"
    action: "add_auxiliary_view"
  - trigger: "part.is_assembly or part.face_count_nonorthogonal > 3"
    action: "add_isometric_view(dimensioned=false)"

gdt_rules:
  - feature: "flat_mounting_face"
    default: "flatness"
    also: "becomes_primary_datum"
  - feature: "clearance_hole_pattern"
    default: "position"
    modifier: "MMC"
    datums: ["A", "B", "C"]
  - feature: "locating_dowel_hole"
    default: "position"
    modifier: "RFS"
    datums: ["A", "B"]
  - feature: "bearing_bore"
    default: ["cylindricity", "position", "perpendicularity"]
    modifier: "RFS"
  - feature: "cast_surface"
    default: "profile_of_surface"

tolerance_defaults:
  general_standard: "ISO 2768-mK"
  fit_system: "hole_basis"
  clearance_fit: "H7/g6"
  transition_fit: "H7/k6"
  interference_fit: "H7/s6"
```

---

## Notes on scope

This document covers the ISO/ASME conventions that govern *why* a
manufacturing drawing looks the way it does — it's meant to close the gap
your tool is hitting (basic dimensioning + basic GD&T only). It does not
include the specific worked examples from any particular textbook; if you
want to feed additional worked examples into the tool, the cleanest path
is to describe your own representative parts (a shaft, a housing, a
bracket) and I can turn those into fully worked, GD&T-complete reference
drawings/rules in the same format — that gives Claude Code concrete
before/after examples to pattern-match against, which usually improves
these tools faster than general rules alone.
