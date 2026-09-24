# Architecture

## Principle

| Component | Role | Status |
|---|---|---|
| OCCT (`services/geometry`) | geometric truth: import, measurement, topology, features | **implemented (M1)** |
| Deterministic algorithms | dimension candidates, view layout, plan validation, QA | planned |
| Deterministic planner (`services/drawing-planner`) | dimension candidates, view choice, redundancy → `DrawingPlan` | **implemented (M2)** |
| Drawing compiler (`services/drawing-compiler`) | `DrawingPlan` → `CompiledDrawing` (layout, scale, placement) | **implemented (M2)** |
| Open-source executor (`services/drawing-executor`) | OCCT HLR + ezdxf → DXF/PDF/SVG | **implemented (M2)** |
| QA (`services/drawing-qa`) | deterministic checks + repair loop (max 3) | **implemented (M2)** |
| SolidWorks worker (Windows, C#) | SLDDRW + DWG (authoritative native drawings) | planned (contract drafted) |
| LLM | optional hook only; **not used** (`CADAI_LLM_BACKEND=none`) | not needed |

No LLM is involved in producing a drawing. Every value on a drawing is traceable to a
GeometryIR field (`candidates.json` records the source of each one).

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
 JobRunner ──► subprocess: python -m drawing_executor generate            (same sandboxing)
                 GeometryIR + DrawingSettings → planner → DrawingPlan → compiler → CompiledDrawing
                 → OCCT HLR per view → DXF (ezdxf) → QA (+ repair ≤ 3) → PDF/SVG/PNG (if no CRITICAL)
 ───────────────────────────── later milestones ─────────────────────────────
 CompiledDrawing → job lease → Windows worker (SolidWorks COM, STA) → SLDDRW / DWG
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
