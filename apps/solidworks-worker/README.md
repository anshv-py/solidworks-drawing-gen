# SolidWorks worker (Windows) - milestone 6

**Not implemented.** No C# code is committed yet because it cannot be compiled or run in
the Linux development environment, and SolidWorks API signatures are not yet verified
(see `.claude/skills/solidworks-api-automation/references/api-verification.md`).

## Contract (draft)
- Input: `DrawingOps` JSON (example: `.claude/skills/solidworks-api-automation/examples/drawing-ops.json`)
  obtained by leasing a job from the API (`POST /api/worker/leases`, worker token).
- Output: `.SLDDRW`, `.pdf`, `.dwg`, optional `.dxf`, preview PNG, `op_log.json`
  (per-op result, API member, HRESULT/errors), `generator: SOLIDWORKS <version>`,
  sha256 per artifact.
- Failure: structured error; never "success" without verified files.

## Planned structure
```
SolidWorksWorker.sln
  src/Worker.Host        Windows service host, lease loop, heartbeat, supervisor
  src/Worker.Core        DrawingOps model, validation, executor interface, mock executor
  src/Worker.SolidWorks  STA dispatcher, SolidWorks session, op handlers (COM only here)
  tests/                 unit tests with mock executor
```
