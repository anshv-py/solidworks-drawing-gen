---
name: cad-drawing-qa
description: Drawing quality assurance for CAD Drawing AI. Activate when designing, implementing or running checks on a generated engineering drawing - view/dimension/annotation overlap, sheet-boundary and title-block collisions, scale and whitespace, missing/duplicate/redundant dimensions, missing center marks/centerlines/hole callouts, wrong view orientation, hidden-line, section/detail view problems, readability, image-based (visual) QA with a vision model, QA severity rules, and the generate→validate→critique→repair→validate loop with configurable retries. Do NOT use for choosing what a drawing should contain in the first place (cad-engineering-automation) or for SolidWorks API calls (solidworks-api-automation).
---

# CAD Drawing QA

QA decides whether a drawing may be released. It is **deterministic first,
visual second**, and it never edits CAD directly.

## Loop

```
GENERATE → VALIDATE (deterministic) → CRITIQUE (visual, optional)
        → REPAIR (plan patch → compiler) → VALIDATE AGAIN
```
- `QA_MAX_RETRIES` (default **3**) bounds the loop.
- Any **CRITICAL** issue remaining after the last retry **blocks export**; the
  job ends `FAILED` with the QA report attached.
- Repairs are expressed as a `DrawingPlanPatch` (typed) → drawing compiler →
  worker. The vision model returns *issues*, never CAD operations.

## Inputs QA needs

1. `GeometryIR` (truth: features, dimension candidates)
2. `DrawingPlan` (intent)
3. `DrawingManifest` from the worker: sheet size, title-block rect, per-view
   outline rect + scale + orientation, per-annotation bounding boxes, dimension
   list with attached entity references and displayed value.
4. Rendered sheet image (PNG from PDF) for visual QA.

## Deterministic check catalogue (IDs are stable - see references/check-catalog.md)

| ID | Check | Default severity |
|---|---|---|
| QA-SHEET-001 | View outline outside sheet border | CRITICAL |
| QA-SHEET-002 | Annotation/dimension outside sheet border | CRITICAL |
| QA-SHEET-003 | Collision with title block | CRITICAL |
| QA-VIEW-001 | View-view overlap | CRITICAL |
| QA-VIEW-002 | View orientation ≠ plan (e.g. FRONT not front) | CRITICAL |
| QA-VIEW-003 | Projection placement inconsistent with projection method | MAJOR |
| QA-VIEW-004 | Scale not an ISO 5455 preferred scale / differs from plan | MAJOR |
| QA-VIEW-005 | Excessive whitespace (views occupy < X % of drawable area) | MINOR |
| QA-DIM-001 | Displayed value ≠ GeometryIR value (after display rounding) | CRITICAL |
| QA-DIM-002 | Required dimension missing (overall extents, every hole Ø) | CRITICAL |
| QA-DIM-003 | Duplicate dimension (same candidate in two places) | MAJOR |
| QA-DIM-004 | Redundant chain (closed loop over-dimensioned) | MAJOR |
| QA-DIM-005 | Dimension-dimension / dimension-view overlap | MAJOR |
| QA-DIM-006 | Dimension attached to hidden edge | MINOR |
| QA-ANN-001 | Hole without center mark in circular view | MAJOR |
| QA-ANN-002 | Cylindrical feature without centerline in side view | MINOR |
| QA-ANN-003 | Hole/pattern without hole callout | MAJOR |
| QA-ANN-004 | Annotation overlap | MAJOR |
| QA-ANN-005 | Text height below minimum (ISO 3098: 2.5 mm on A3) | MAJOR |
| QA-REF-001 | Dimension/callout references a missing feature/entity | CRITICAL |
| QA-SEC-001 | Section line without matching section view (or vice versa) | CRITICAL |
| QA-DET-001 | Detail circle without detail view / wrong scale label | MAJOR |
| QA-TB-001 | Engineering info field invented (value without USER/CAD source) | CRITICAL |

Geometry in QA is 2D axis-aligned rectangles in sheet mm; overlap uses a
configurable clearance (default 2 mm).

## Visual QA (optional)

Render the sheet at ≥ 150 dpi, send to the vision model with the plan summary
and ask for issues in the **structured** `VisualQaReport` schema (issue type,
bbox in normalized sheet coords, severity suggestion, explanation). Visual
findings are **advisory** unless confirmed by a deterministic check; they may
raise a MINOR/MAJOR issue but cannot on their own mark something CRITICAL
unless configured.

## Reporting

`QaReport{ drawing_id, iteration, passed, issues[{id, check_id, severity,
message, entity_refs, bbox, suggested_repair}], summary counts }`. Store every
iteration's report for traceability.

## Implementation status
The deterministic checks are implemented in `services/drawing-qa/src/drawing_qa/checks.py`;
`docs/QA.md` lists the implemented IDs and severities, which take precedence over the catalogue
below where they differ. Visual QA is not implemented.

## References
- `references/check-catalog.md` - check definitions, inputs, thresholds
- `references/repair-strategies.md` - issue → plan patch mapping
- `examples/qa-report.json` - example report
- `examples/visual-qa-prompt.md` - structured visual-QA prompt contract
