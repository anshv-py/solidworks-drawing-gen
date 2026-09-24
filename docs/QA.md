# Drawing QA (design - not implemented)

Loop: GENERATE → VALIDATE (deterministic) → CRITIQUE (visual, optional) → REPAIR (plan patch
→ compiler) → VALIDATE AGAIN; `CADAI_QA_MAX_RETRIES` (default 3). Any CRITICAL issue left after
the last retry blocks export (job FAILED with the report).

Check catalogue, severities and thresholds: `.claude/skills/cad-drawing-qa/references/check-catalog.md`.
Visual QA returns structured issues only (`VisualQaReport`) and cannot modify CAD.

Milestone-1 QA that *is* in place: geometry-level validation (BRepCheck, watertightness,
unit handling, ID/reference integrity tests, schema strictness).
