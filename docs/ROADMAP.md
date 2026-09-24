# Roadmap

| # | Milestone | Status |
|---|---|---|
| 0 | Claude skills, project instructions, knowledge structure | ✅ done |
| 1 | STEP/STL → OCCT → GeometryIR → features → API → 3D preview | ✅ done, tested |
| 2 | **Dimension-candidate engine + deterministic planner baseline** | ⏭ next |
| 3 | LLM planner (structured DrawingPlan) + plan validator | planned |
| 4 | Drawing compiler (view layout, ISO 5455 scale, DrawingOps) + mock executor | planned |
| 5 | Job system hardening: RQ runner, SSE progress, Alembic, auth | planned |
| 6 | SolidWorks Windows worker (verified API, STA, leasing, exports) | planned |
| 7 | Deterministic QA + repair loop | planned |
| 8 | Visual QA (rendered sheet → structured issues) | planned |
| 9 | STL feature recognition (segmentation + primitive fitting) | planned |
| 10 | End-to-end evaluation vs reference drawings | planned |

## Next milestone (2) - exact scope
1. `services/drawing-planner`: `DimensionCandidate` schema (id, kind, value from GeometryIR,
   entity refs, preferred view direction, priority) in `packages/drawing-schema`.
2. Candidate generation for: overall extents; hole Ø + depth/THRU; hole positions relative to
   bbox faces; pattern PCD/pitch; pocket L/W/depth; slot width/length; fillet R; chamfer legs;
   boss Ø/height.
3. View-direction assignment (which orthographic view shows each candidate true-size).
4. Redundancy rules (pattern members share one callout; no closed chains).
5. `plan_baseline(geometry, settings) -> DrawingPlan` (no LLM), plus referential validation of
   candidate ids against GeometryIR.
6. Tests on all fixtures (e.g. flange → 8X Ø8 THRU on PCD Ø86 as one candidate; mounting plate →
   counterbore callouts), API `POST /api/drawings/plan` (dry-run plan preview), UI list of planned
   dimensions.

## Open questions / verification debt
- SolidWorks API signatures (register in the solidworks skill) - unverified.
- GeometryIR→SolidWorks orientation mapping.
- DeepSeek-V4-Pro: confirm `transformers` loading requirements (version, `trust_remote_code`), JSON-schema
  constrained decoding options, and GPU sizing from the model card (huggingface.co was unreachable from the
  build sandbox). Visual QA needs a vision-capable model; whether V4-Pro accepts images is unverified.
- Docker image with `libgl1` not built in sandbox (Debian mirror blocked).
