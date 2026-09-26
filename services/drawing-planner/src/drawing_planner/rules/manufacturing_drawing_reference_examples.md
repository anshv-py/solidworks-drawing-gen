# Manufacturing Drawing Reference Examples & Automation Gate
### Companion to `manufacturing_drawing_rules.md` — worked examples + the universal baseline every drawing must satisfy, written so a CAD-update can trigger automatic regeneration and validation.

This file has two jobs:
1. **Section 1–2**: define the *non-negotiable minimum* every single drawing
   must contain, and the automation loop that fires on every CAD change.
2. **Section 3+**: fully worked reference examples (shaft, housing, bracket,
   flange) showing the rules file applied end-to-end — feature list → datum
   scheme → view plan → dimensions → GD&T → finish → release notes. These
   are meant to be cloned/adapted by the tool as templates for the nearest-
   matching part archetype, not copied verbatim.

---

## 1. Universal Mandatory Minimum (applies to EVERY drawing, no exceptions)

Nothing below is optional or part-type-dependent. If a CAD update produces a
drawing missing any of these, the drawing is **not manufacturing-ready** and
must be flagged, regardless of how good the dimensioning/GD&T otherwise is.

| # | Requirement | Machine-checkable condition |
|---|---|---|
| 1 | Title block complete | part number, revision, material spec, drawing scale, sheet size, projection-angle symbol, "units" declaration all non-empty |
| 2 | General tolerance note present | one note referencing a tolerance standard (e.g., ISO 2768-mK) covers every undimensioned tolerance — must exist even if every other dimension is individually toleranced |
| 3 | Default surface finish note present | one blanket finish callout (e.g., Ra 3.2 unless noted) even if specific surfaces override it |
| 4 | Datum reference frame declared | at least Datum A exists on any part with ≥1 GD&T callout; every position/orientation callout references a declared datum, never a floating letter |
| 5 | Every solid feature dimensioned or covered by general tolerance | zero geometry with no traceable dimension/tolerance source (auto-diff against CAD feature tree) |
| 6 | No duplicate dimensions | each dimension value appears on exactly one view |
| 7 | Every fastener/thread feature fully designated | full thread callout (standard, size, pitch, class, depth) — never a bare diameter on a tapped hole |
| 8 | Every mating/functional feature has explicit tolerance or GD&T | nothing functionally critical left to the general block |
| 9 | Break/section/detail/auxiliary views added per Section 1 of the rules file wherever their trigger condition is met | re-run the view-trigger checks after every geometry change, not just at first generation |
| 10 | Units and standard consistent sheet-wide | one unit system, one tolerance standard, no mixing |
| 11 | Revision block updated | every regenerated drawing increments/logs a revision entry, even for automated regenerations, so change history is traceable |
| 12 | Weight/material block (if company standard requires it) | populated from CAD mass properties, not left blank |

**Gate rule:** treat items 1–8 and 11 as **hard blockers** (drawing cannot be
released/exported until satisfied). Treat 9–10, 12 as **warnings** the tool
should auto-fix silently when possible (e.g., auto-insert the missing break
line) and only surface to a human if it can't resolve them automatically.

---

## 2. Automation Pipeline (fires on every CAD update)

```
on cad_model_changed(part):
    1. diff_features(old_tree, new_tree)
         -> list of: added / removed / modified features (holes, bosses,
            fillets, faces, threads, patterns)

    2. for each changed feature:
         re-evaluate view_rules   (rules file §1)
         re-evaluate dimension_rules (rules file §2)
         re-evaluate gdt_rules    (rules file §4)
         re-evaluate finish_rules (rules file §5)
       -> only regenerate the views/dimensions/callouts actually affected;
          do not blindly regenerate the whole sheet (preserves manual
          adjustments the engineer made elsewhere on the drawing)

    3. re-run Universal Mandatory Minimum checklist (this file §1)
         -> if hard blocker fails: HALT, flag part+reason, do not release
         -> if warning-level fails: auto-fix if a deterministic fix rule
            exists (Section 2 pattern library below), else flag for review

    4. re-validate datum scheme still valid
         -> if a feature that was Datum A/B/C was deleted or moved,
            re-run datum selection (rules file §4.1) — do NOT silently
            leave a feature control frame referencing a datum that no
            longer exists

    5. increment revision, log diff summary in the revision block

    6. output: updated drawing + machine-readable "compliance report"
       (pass/fail per checklist item) so the human reviewer sees exactly
       what changed and why, not just a new sheet to re-check from scratch
```

**Key design point:** the automation should be *incremental and diff-driven*,
not a full regenerate-from-scratch on every change. A tool that regenerates
everything on every tweak will fight the engineer's manual placement/cleanup
work every time. Only features that changed should trigger rule re-evaluation.

---

## 3. Worked Reference Example A — Precision Shaft (turned part)

**Part context:** stepped shaft, two bearing seats, one keyway, one threaded
end for a retaining nut, made from 4140 steel, turned + ground on the
bearing seats.

**Feature list**
| Feature | Description |
|---|---|
| F1 | Ø20 h6 bearing seat, left end, 25 mm long |
| F2 | Ø28 shoulder, 3 mm tall, locates bearing inner race |
| F3 | Ø24 h6 bearing seat, right end, 20 mm long |
| F4 | M18x1.5-6g external thread, 15 mm long, right end, for retaining nut |
| F5 | 6 mm wide x 3 mm deep keyway, 30 mm long, mid-shaft |
| F6 | 1x45° chamfers, both ends |
| F7 | Overall length 180 mm |

**Datum scheme**
- **Datum A** = axis of the two bearing seats (F1 & F3), established as a
  common datum axis (A) taken from the two functional bearing diameters
  themselves — this is the axis the part actually rotates about in service.
- **Datum B** = the shoulder face (F2), fixes axial position.
- No Datum C needed — the keyway is located angularly relative to A only;
  rotational reference isn't functionally critical beyond the keyway itself,
  so the keyway's own position callout carries its own angular reference,
  not a separate datum.

**View plan** (per rules file §1)
- 1 primary view (front, shaft horizontal) — axisymmetric part, this is the
  §1.1 "2-view" case: front view + one end view.
- 1 end view (right end) to show keyway width and depth without hidden lines
  stacking — triggers §1.3 by the "feature needing >2 hidden-line callouts"
  rule for the keyway.
- No isometric — simple turned part, fails all §1.2 triggers.
- Detail view on the keyway if drawn below 1:2 scale (per §1.4); at 1:1 or
  larger, not required.
- No section view needed — no internal/blind features exist on this part.

**Dimension set**
| Dim | Nominal | Tolerance | Type |
|---|---|---|---|
| Ø20 (F1) | 20 | h6 (limits table, ISO 286) | Diameter, mating |
| Ø28 (F2) | 28 | ±0.1 | Diameter, non-mating shoulder |
| Ø24 (F3) | 24 | h6 | Diameter, mating |
| M18x1.5 (F4) | — | per thread class 6g | Thread designation |
| Keyway width (F5) | 6 | N9 (per ISO fit for keyways) | Width |
| Keyway depth (F5) | 3 | +0.1/0 | Depth |
| Keyway length (F5) | 30 | ±0.2 | Length |
| Overall length (F7) | 180 | ±0.3 | General tolerance (from block) is NOT enough here since it drives bearing spacing — explicit tol given |
| Chamfers (F6) | 1x45° | general tolerance | Standard shorthand |

**GD&T callouts**
| Feature | Symbol | Tolerance zone | Modifier | Datum(s) |
|---|---|---|---|---|
| F1 (Ø20 bearing seat) | Cylindricity | 0.005 | — | none (form only) |
| F3 (Ø24 bearing seat) | Cylindricity | 0.005 | — | none (form only) |
| F1 | Circular runout | 0.02 | — | A |
| F3 | Circular runout | 0.02 | — | A |
| F2 (shoulder face) | Perpendicularity | 0.02 | — | A |
| F5 (keyway) | Position (symmetric) | 0.1 | Ⓜ | A |
| F4 (thread pitch dia.) | Position | per thread pitch dia. tolerance | Ⓜ | A |

**Surface finish**
| Surface | Ra |
|---|---|
| F1, F3 (bearing seats) | 0.4 µm (ground) |
| F2 (shoulder face) | 1.6 µm |
| General turned surfaces | 3.2 µm (blanket note) |

**Release notes / title block additions:** material 4140 steel, heat treat
callout if hardened bearing seats required (e.g., "induction harden F1, F3
to 50-55 HRC, 1 mm case depth"), general tolerance ISO 2768-mK, projection
angle per company standard.

---

## 4. Worked Reference Example B — Machined Housing / Block

**Part context:** aluminum housing, one primary mounting face, one bearing
bore, four clearance holes for mounting bolts, one tapped hole for a grease
fitting, cast rough shape then machined on critical faces/bores.

**Feature list**
| Feature | Description |
|---|---|
| F1 | Bottom mounting face (machined flat) |
| F2 | Ø40 H7 bearing bore, through, perpendicular to F1 |
| F3 | 4x Ø6.5 clearance holes on a 70x50 bolt pattern, from F1 |
| F4 | M6x1-6H tapped hole for grease fitting, side face |
| F5 | Cast outer walls/ribs (as-cast, non-machined) |
| F6 | 2x locating dowel holes, Ø5 H7, near two diagonal corners of bolt pattern |

**Datum scheme**
- **Datum A** = F1, the mounting face — primary, removes 3 DOF (largest
  functional contact face, matches how the part is fixtured and mounted).
- **Datum B** = axis of F2, the bearing bore — secondary, removes 2 DOF
  (this is what all the bolt/dowel positions are functionally aligned to).
- **Datum C** = one of the dowel holes (F6) — tertiary, removes final
  rotational DOF.

**View plan**
- 3 orthographic views (front, top, right) — standard prismatic block, §1.1
  3-view default.
- **Section view A-A** through F2 (bearing bore) — triggers §1.3: internal
  bore with a fit tolerance (H7) cannot be clearly dimensioned via hidden
  lines alone.
- **Isometric view added** — triggers §1.2: cast part with ribs (F5) and
  non-obvious wall geometry; isometric added for clarity only, not
  dimensioned.
- No auxiliary view — no angled faces carrying dimensioned features in this
  example.
- Detail view on F4 (small tapped hole) if drawing scale is below 1:2.

**Dimension set**
| Dim | Nominal | Tolerance | Type |
|---|---|---|---|
| Ø40 (F2) | 40 | H7 | Diameter, mating (bearing bore) |
| Bolt pattern (F3) | 70 x 50 | baseline from A/B, ±0.15 | Position (baseline, see GD&T table for actual control) |
| Ø6.5 (F3) | 6.5 | +0.2/0 | Diameter, clearance |
| M6x1 (F4) | — | class 6H | Thread designation |
| Ø5 (F6) dowel holes | 5 | H7 | Diameter, locating |
| Overall envelope | per CAD | general tolerance | Non-functional |

**GD&T callouts**
| Feature | Symbol | Tolerance zone | Modifier | Datum(s) |
|---|---|---|---|---|
| F1 (mounting face) | Flatness | 0.05 | — | none (becomes Datum A) |
| F2 (bearing bore) | Cylindricity | 0.01 | — | none (form only) |
| F2 | Perpendicularity | 0.02 | — | A |
| F2 | Position | 0.05 | — | A (bore itself often IS datum B — no self-referencing position needed if it's the datum feature) |
| F3 (4x clearance holes, pattern) | Position | Ø0.4 | Ⓜ | A\|B\|C |
| F6 (2x dowel holes) | Position | Ø0.1 | RFS | A\|B |
| F4 (tapped hole) | Position | Ø0.3 | Ⓜ | A\|B |

Note the **composite tolerancing opportunity** on F3: pattern-locating
tolerance (Ø0.4 to A|B|C, looser) plus a feature-relating-to-feature
tolerance (tighter, fewer datums) if bolt-to-bolt spacing within the pattern
matters more than the pattern's location to the bore — apply per rules file
§4.5 composite-frame trigger.

**Surface finish**
| Surface | Ra |
|---|---|
| F1 (mounting face) | 1.6 µm |
| F2 (bearing bore) | 0.8 µm |
| F3, F6 (drilled holes) | 3.2 µm (as-drilled, default) |
| F5 (as-cast walls) | no callout — general note "AS CAST" |

**Release notes:** material (e.g., A356-T6 aluminum), general tolerance
ISO 2768-mK, casting draft angle note if relevant, heat-treat/temper
callout if applicable.

---

## 5. Worked Reference Example C — Sheet-Metal L-Bracket

**Part context:** 2 mm steel bracket, one 90° bend, two mounting slots on
the base leg, two clearance holes on the vertical leg.

**Feature list**
| Feature | Description |
|---|---|
| F1 | Base leg, flat, with 2x mounting slots |
| F2 | 90° bend, internal radius 2 mm (= material thickness, standard) |
| F3 | Vertical leg, flat, with 2x Ø6.5 clearance holes |
| F4 | 2x slots, 8 mm wide x 16 mm long, on base leg |
| F5 | Flat pattern (unfolded) overall dimensions, for the fabricator |

**Datum scheme**
- **Datum A** = underside of F1 (base leg) — the face that sits on the
  mating surface in assembly.
- **Datum B** = one edge of F1 (a machined/laser-cut edge, not the bend) —
  secondary, locates in-plane position.
- **Datum C** = edge of F3 perpendicular to B, or an inside face of the
  bend — tertiary, if the vertical leg's angular position needs control
  beyond the nominal 90°.

**View plan**
- 3 orthographic views (front showing the bend profile, top, side).
- **Isometric view added** — triggers §1.2 (sheet metal with a bend; bend
  direction is far clearer pictorially than in flat orthographic views).
- **Flat pattern view added on a separate "FLAT PATTERN" view/sheet** —
  this is sheet-metal-specific and not covered by the general rules file;
  add it as a rule: *any sheet-metal part must include a flat-pattern view
  with overall unfolded dimensions and bend-line call-outs (bend angle,
  bend radius, bend direction up/down) in addition to the formed-state
  views.*
- No section view needed (no internal features).

**Dimension set**
| Dim | Nominal | Tolerance | Type |
|---|---|---|---|
| Bend angle (F2) | 90° | ±0.5° | Angular |
| Bend radius (F2) | 2 mm (=material thickness) | general tolerance | Radius |
| Slot width (F4) | 8 | +0.2/0 | Width |
| Slot length (F4) | 16 | ±0.2 | Length |
| Ø6.5 holes (F3) | 6.5 | +0.2/0 | Diameter |
| Flat pattern length | per CAD unfold | ±0.3 | Overall, fabrication reference |

**GD&T callouts** (sheet metal typically uses lighter GD&T than machined
parts — apply only where function demands it, do not over-specify thin
formed parts)
| Feature | Symbol | Tolerance zone | Datum(s) |
|---|---|---|---|
| F1 underside | Flatness | 0.3 (loose — thin sheet, avoid over-constraining a flexible part) | none |
| F4 (slots) | Position | 0.4 | A\|B |
| F3 holes | Position | 0.4 | A\|B\|C |

**Surface finish:** typically no explicit Ra callout on sheet metal;
finish is governed by the material spec/coating note (e.g., "ZINC PLATE
PER ASTM B633") instead of a roughness value.

**Release notes:** material + gauge (e.g., "2mm CRS, mild steel"), bend
allowance/K-factor note if fabricator requires it, finish/coating spec,
grain direction note if the material has a rolling direction that affects
bend cracking risk.

---

## 6. Worked Reference Example D — Bolted Flange / Cover Plate

**Part context:** circular cover plate, one O-ring sealing face, 6-hole
bolt circle, one central through-bore.

**Feature list**
| Feature | Description |
|---|---|
| F1 | Sealing face (flat, faces the O-ring groove side) |
| F2 | O-ring groove, Ø45 x 3 mm wide x 2.5 mm deep |
| F3 | Central through-bore, Ø30 |
| F4 | 6x Ø8.5 clearance holes on Ø80 bolt circle |
| F5 | Outer diameter Ø100 |

**Datum scheme**
- **Datum A** = F1 (sealing face) — primary, this is the assembly contact
  face.
- **Datum B** = axis of F3 (central bore) — secondary, the pattern's
  functional center.
- No Datum C — a 6-hole pattern on a bolt circle is rotationally symmetric
  every 60°, so no tertiary angular datum is meaningful; position tolerance
  on the pattern (referencing A|B only) is sufficient.

**View plan**
- 2 views: front (circular face) + one section view — triggers §1.1 (2-view
  axisymmetric case) plus §1.3 (O-ring groove is an internal-profile feature
  that must be sectioned to dimension groove width/depth correctly).
- No isometric needed — simple axisymmetric part, fails §1.2 triggers.
- Detail view on the O-ring groove profile if drawn below 1:1 (groove
  corner radii and depth are typically tight-toleranced — triggers §1.4).

**Dimension set**
| Dim | Nominal | Tolerance | Type |
|---|---|---|---|
| Ø100 (F5) | 100 | ±0.2 | Diameter, overall |
| Ø30 (F3) | 30 | H8 | Diameter, through-bore |
| Groove Ø45 (F2) | 45 | ±0.1 | Diameter, groove centerline |
| Groove width (F2) | 3 | +0.1/0 | Width, per O-ring vendor spec |
| Groove depth (F2) | 2.5 | +0.05/0 | Depth, per O-ring vendor spec |
| Bolt circle Ø80 (F4) | 80 | basic (theoretical) | Position basic dimension |
| Ø8.5 (F4) | 8.5 | +0.2/0 | Diameter, clearance |

**GD&T callouts**
| Feature | Symbol | Tolerance zone | Modifier | Datum(s) |
|---|---|---|---|---|
| F1 (sealing face) | Flatness | 0.03 | — | none (becomes Datum A) |
| F1 | Surface finish only, no additional GD&T beyond flatness | — | — | — |
| F3 (through-bore) | Perpendicularity | 0.05 | — | A |
| F4 (6x bolt holes) | Position | Ø0.3 | Ⓜ | A\|B |
| F2 (groove, as a profile) | Profile of a surface | 0.05 | — | A\|B (controls both groove location and cross-section shape in one callout — preferred over separately dimensioning every groove wall) |

**Surface finish**
| Surface | Ra |
|---|---|
| F1 (sealing face) | 0.8 µm, "no radial lay" note (radial scratches defeat O-ring sealing) |
| F2 (groove walls) | 1.6 µm |
| General | 3.2 µm |

---

## 7. Cross-Part Pattern Library (what the automation should recognize)

This table is the fast lookup the tool should hit first, before falling
back to the full decision trees in the rules file — it's the distilled
"if you see this feature, do this" table drawn from the four examples
above.

| Recognized feature pattern | Auto-applied treatment |
|---|---|
| Largest flat face used for mounting/fixturing | → Datum A, flatness callout, no position needed (it defines the frame) |
| Bore that a bearing/bushing presses into | → Cylindricity + perpendicularity/position to Datum A, RFS, Ra 0.8–1.6 |
| Bore/shaft that's a rotating datum axis | → circular or total runout, common datum axis if two coaxial features share it |
| Clearance hole in a bolted pattern | → Position at MMC, referenced to full datum stack, loose (+0.2/0) size tolerance |
| Locating/dowel hole | → Position at RFS, tight (H7) size tolerance, fewer datums (usually A|B only) |
| Tapped hole | → full thread designation + Position (usually MMC) — never a bare diameter |
| O-ring groove / seal face | → Flatness on the face + Profile of surface on the groove, "no radial lay" finish note |
| Cast/molded external wall | → Profile of a surface, no tight tolerance, general note "AS CAST"/"AS MOLDED" |
| Sheet-metal bend | → angular tolerance + radius note + mandatory flat-pattern view |
| Any internal cavity/bore not visible in standard views | → section view, automatically, no exception |
| Any feature toleranced tighter than the general block | → automatically pulled into a detail view if drawing scale would make it illegible |
| Complex/organic/cast/multi-rib geometry | → isometric view added, non-dimensioned, for clarity |
| Repeating identical small feature (array) | → dimension one instance, "X PLACES/TYP" note, not every instance individually |

---

## 8. Automated Validation / QA Rule Set (run before every release)

```
def validate_drawing(drawing, cad_model):
    errors = []
    warnings = []

    # Hard blockers — Universal Mandatory Minimum, Section 1 above
    if not drawing.title_block.complete(): errors.append("Incomplete title block")
    if not drawing.has_general_tolerance_note(): errors.append("Missing general tolerance note")
    if not drawing.has_default_finish_note(): errors.append("Missing default surface finish note")
    if drawing.has_any_gdt() and not drawing.datum_frame.is_valid():
        errors.append("GD&T present without valid datum reference frame")
    if cad_model.has_undimensioned_geometry(drawing): errors.append("Undimensioned feature(s) found")
    if drawing.has_duplicate_dimensions(): errors.append("Duplicate dimension(s) across views")
    for hole in cad_model.tapped_holes():
        if not drawing.has_full_thread_designation(hole): errors.append(f"Incomplete thread callout: {hole.id}")
    for feature in cad_model.functional_mating_features():
        if not drawing.has_explicit_tolerance_or_gdt(feature):
            errors.append(f"Functional feature lacks explicit tolerance: {feature.id}")
    if not drawing.revision_block.updated_this_change(): errors.append("Revision block not updated")

    # Warnings — auto-fixable
    for feature in cad_model.features_needing_section(): 
        if not drawing.has_section_for(feature):
            warnings.append(f"Missing required section view: {feature.id} -> auto-adding")
            drawing.add_section_view(feature)
    for feature in cad_model.features_needing_detail():
        if not drawing.has_detail_for(feature):
            warnings.append(f"Missing required detail view: {feature.id} -> auto-adding")
            drawing.add_detail_view(feature)
    if cad_model.is_complex_shape() and not drawing.has_isometric():
        warnings.append("Complex part missing clarity isometric -> auto-adding")
        drawing.add_isometric_view(dimensioned=False)

    return errors, warnings   # errors block release; warnings are logged + auto-fixed
```

---

## 9. How to extend this library

When a new part doesn't match any pattern in Section 7, add it as a new
worked example in this same format (feature list → datum scheme → view
plan → dimension set → GD&T table → finish table → release notes), then
add its distilled pattern(s) to the Section 7 lookup table. This keeps the
tool's "thinking" grounded in a growing set of concrete precedents instead
of re-deriving first principles on every new part shape.
