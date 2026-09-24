# Architecture

## Principle

| Component | Role | Status |
|---|---|---|
| OCCT (`services/geometry`) | geometric truth: import, measurement, topology, features | **implemented (M1)** |
| Deterministic algorithms | dimension candidates, view layout, plan validation, QA | planned |
| DeepSeek-V4-Pro (Hugging Face `transformers`, GPU planner worker) | reasoning/planning → `DrawingPlan` only | planned |
| Drawing compiler | `DrawingPlan` → ordered `DrawingOps` | planned |
| SolidWorks worker (Windows, C#) | authoritative drawing generation + export | planned (contract drafted) |
| QA | deterministic + visual checks, repair loop (max 3) | planned |

The LLM never issues CAD API calls and never supplies numbers. Every value on a
drawing is traceable to a GeometryIR entity id.

## Data flow

```
 Browser (React/Three.js)
    │ upload / poll / fetch
    ▼
 FastAPI (cad_api) ── SQL ──► PostgreSQL (models, jobs)
    │ submit                   Storage (root-confined, UUID paths)
    ▼
 JobRunner ──► subprocess: python -m geometry_service analyze   (timeout, RLIMIT_AS, own cwd/env)
                 │ OCCT: STEP/STL → topology → properties → convexity → features → IDs
                 ├─ geometry_ir.json   (GeometryIR, Pydantic-validated)
                 └─ preview_mesh.json  (per-face triangle groups + edge polylines)
 ───────────────────────────── later milestones ─────────────────────────────
 GeometryIR + user settings → planner (rules + LLM) → DrawingPlan → validator → compiler
   → DrawingOps → job lease → Windows worker (SolidWorks COM, STA) → SLDDRW/PDF/DWG/DXF
   → QA (deterministic + visual) → repair via plan patch → final artifacts
```

## Contracts (packages/)

- `geometry-schema` - **GeometryIR** (see GEOMETRY.md). Strict (`extra=forbid`), immutable.
- `drawing-schema` - **DrawingPlan**: views, sections, details, dimension *selections by
  candidate id* (no value field), annotations, engineering information with explicit
  `UNSPECIFIED` + source. A MANUFACTURING plan is rejected unless material and general
  tolerance are supplied.
- JSON Schemas are exported to `packages/*/schema/` and compiled to TypeScript
  (`apps/frontend/src/generated`); CI fails on drift.

## Isolation & security

- API never imports OCCT or SolidWorks. CAD parsing: one subprocess per job, fixed argv,
  minimal env, per-job working directory, address-space limit, wall-clock timeout,
  structured JSON-lines protocol (native library output diverted to stderr).
- Uploads: extension allowlist + content sniffing (STEP header, STL binary size formula /
  ASCII grammar) + streamed size limit; server-generated storage names; traversal-safe paths.
- `get_principal()` dependency on every route; rows carry `owner_id` (auth-ready).

## Key decisions
See `references/architecture/decisions.md`.
