---
name: solidworks-api-automation
description: SolidWorks API / COM automation for the CAD Drawing AI Windows worker. Activate when writing or reviewing C#/.NET code that drives SolidWorks (SldWorks, IModelDoc2, IModelDocExtension, IDrawingDoc, IView, IAnnotation), creating drawing views/sections/details, inserting dimensions, center marks, centerlines, hole callouts, applying drawing templates/sheet formats, saving SLDDRW, exporting DWG/DXF/PDF, managing the SolidWorks process and COM object lifecycle, or designing the worker's job protocol and error handling. Do NOT use for deciding what the drawing should contain (use cad-engineering-automation), geometry extraction (use occt-geometry-step), or QA rules (use cad-drawing-qa).
---

# SolidWorks API Automation

SolidWorks is the **authoritative drawing-generation engine**. The worker
executes a deterministic, pre-compiled list of drawing operations
(`DrawingOps`) - it never receives free-form LLM output.

## Hard rules

1. **Never invent API members.** Use only members listed in
   `references/api-verification.md` with status `VERIFIED-SIGNATURE`, or
   verify them against the official API help
   (https://help.solidworks.com/<year>/english/api/sldworksapi/...) for the
   installed SolidWorks version *before* use. If a member is not verified,
   write `// UNVERIFIED: <member> - confirm signature in API help for SW <year>`
   and do not ship it.
2. **Never claim success without evidence.** A step succeeded only if the API
   returned a success value/non-null object *and* post-conditions hold (e.g.
   exported file exists, size > 0, opens). Record `errors`/`warnings` out
   parameters verbatim.
3. **Mock ≠ real.** In mock mode artifacts are labelled `generator: MOCK` and
   carry a visible watermark; never report them as SolidWorks output.
4. **COM only in the Windows worker.** Never from FastAPI / Linux services.
5. **Units:** the SolidWorks API uses **meters and radians** for positions,
   lengths and angles, independent of document units. Convert at one boundary
   (`Units.MmToM`). GeometryIR is in mm.

## Input contract
The worker will consume `CompiledDrawing` (`packages/drawing-schema/src/drawing_schema/compiled.py`),
the same executor-neutral sheet description that the open-source OCCT/ezdxf executor draws
today. `examples/drawing-ops.json` is an earlier sketch.

## Worker architecture (see `references/worker-architecture.md`)

```
job lease (HTTP pull from API)  →  validate DrawingOps JSON (schema version)
  → SolidWorksSession (dedicated STA thread, one SW process per worker)
     open/import model → NewDocument(template) → views → annotations
     → dimensions → save SLDDRW → export PDF/DWG/DXF → verify files
  → upload artifacts + structured op log → release job
  → close docs; recycle SW process every N jobs or on any COM fault
```

- **STA thread:** all COM calls on one dedicated STA thread; SolidWorks COM
  objects are apartment-sensitive.
- **Process isolation:** one SolidWorks instance per worker process; the
  supervisor kills and restarts it on hang (watchdog timeout per op) or on
  `COMException` with RPC codes (`RPC_E_SERVERFAULT`, `RPC_E_DISCONNECTED`).
- **Idempotency:** each op has an ID; the op log records result per op so a
  retry can resume or fail cleanly.
- **Cleanup:** `CloseDoc` every document opened by the job, release RCWs
  (`Marshal.ReleaseComObject` / `FinalReleaseComObject` for long-lived refs),
  delete the job temp dir.

## Import path for neutral files

STEP/STL → `SldWorks.LoadFile4` (import) or `OpenDoc6` for native parts → save
as a temporary `.SLDPRT` in the job directory → reference that path when
creating views. Import options (e.g. STEP import as solid/surface, STL import as
solid body/graphics/surface) must be set explicitly and verified; STL imported as
graphics-only bodies **cannot** be dimensioned reliably - flag this.

## Coordinate mapping

DrawingPlan view names (`FRONT`, `TOP`, `RIGHT`, `ISOMETRIC`...) map to
SolidWorks named model views (commonly written `*Front`, `*Top`, `*Isometric`;
the exact accepted strings are UNVERIFIED - confirm on the target install).
Model orientation must be decided so that GeometryIR's front view matches
SolidWorks' `*Front`; the compiler emits an explicit orientation transform if
needed.

## Error handling

| Failure | Action |
|---|---|
| API returns null / false | op FAILED with member name + args; stop or skip per op criticality |
| `errors`/`warnings` out param non-zero | decode with `swFileLoadError_e` / `swFileSaveError_e` etc.; record |
| COMException RPC fault | mark SW process dead, restart, retry the job once |
| Op timeout | kill SW process, fail job with `TIMEOUT` |
| Export file missing / 0 bytes | FAILED, never COMPLETED |

## References

- `references/api-verification.md` - every API member we use, with verification status
- `references/worker-architecture.md` - process model, job protocol, lifecycle
- `references/export-formats.md` - SLDDRW/DWG/DXF/PDF notes and caveats
- `examples/drawing-ops.json` - example compiled op list the worker consumes
- `examples/SessionPattern.cs.md` - STA + COM lifecycle pattern (illustrative, API calls marked with verification status)
