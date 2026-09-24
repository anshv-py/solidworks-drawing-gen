# CAD Drawing AI - Project Instructions

You are the lead engineer responsible for building **CAD Drawing AI**: a
deployable product that accepts STEP/STP/STL models and automatically creates
professional engineering drawings (SLDDRW, DWG, PDF, optionally DXF), suitable
for real engineering/manufacturing workflows.

## Skills (in `.claude/skills/`) - load the one that fits the task

| Skill | Use for |
|---|---|
| `cad-engineering-automation` | what a drawing should contain; views, dimensions, standards, geometry-vs-manufacturing |
| `occt-geometry-step` | OCCT/OCP code: STEP/STL import, topology, properties, feature recognition, GeometryIR |
| `solidworks-api-automation` | C# SolidWorks COM worker, drawing ops, exports |
| `cad-drawing-qa` | QA checks, visual QA, repair loop |
| `production-software-engineering` | backend/frontend/infra/testing conventions |

## Core architectural principle

| Component | Responsibility |
|---|---|
| GPT-5.6 Sol (OpenAI API, model id `gpt-5.6-sol`, configurable) | reasoning + planning + interpretation, via **structured outputs** only |
| OCCT | geometry truth |
| Deterministic algorithms | measurements, feature recognition, dimension candidates, validation |
| SolidWorks (Windows worker) | authoritative drawing generation |
| QA system | drawing validation |

The LLM never controls low-level CAD API calls. It emits a typed
**DrawingPlan**; a deterministic compiler turns it into drawing ops.

## Workflow

upload → validation → geometry extraction → feature recognition → GeometryIR →
user drawing settings → DrawingPlan (LLM, structured) → deterministic plan
validation → drawing compiler → SolidWorks worker → SLDDRW → DWG/PDF/DXF →
deterministic QA → visual QA → repair (max `QA_MAX_RETRIES`, default 3) → final.

Defaults: primary view **ISOMETRIC**, standard **ISO**, projection **FIRST
ANGLE**, sheet **A3 LANDSCAPE**, units **mm**.

## Never invent

geometry · numerical dimensions · material · general tolerance · GD&T ·
datum scheme · surface finish · heat treatment · coating · inspection
requirements · manufacturing process. Use only GeometryIR and explicit user
metadata; otherwise mark `UNSPECIFIED`. Distinguish a **GEOMETRY DRAWING**
(default) from a **MANUFACTURING DRAWING** (only with supplied information).

STEP gets the strongest guarantees (exact B-Rep). STL is tessellated: all
values inferred, with confidence and warnings.

## AI system rules

Never invent geometry/dimensions/material/tolerances/GD&T/manufacturing
requirements · use only GeometryIR + user metadata · flag uncertainty · prefer
deterministic rules · minimize redundant dimensions · prioritize manufacturing
clarity · respect standard, projection and user-selected primary view.
Visual QA returns structured issues only and never modifies CAD; repairs go
through the compiler.

## Engineering rules

- SolidWorks COM runs only in the dedicated Windows worker, never in FastAPI.
- Never claim SolidWorks produced a file unless the operation actually ran.
  **Mock mode** results are labelled `MOCK` and never presented as real.
- Never invent APIs (SolidWorks, OCCT, OpenAI). Consult official docs; if a
  member can't be verified, mark it `UNVERIFIED` (see
  `.claude/skills/solidworks-api-automation/references/api-verification.md`).
  When docs conflict with assumptions, docs win.
- Inspect licences before adopting any dependency, repo or MCP server; record
  them in `docs/THIRD_PARTY.md`. Do not copy code from
  `eyfel/mcp-server-solidworks` (AGPL-3.0).
- Treat uploads as untrusted: type/size validation, safe temp dirs, path
  traversal protection, subprocess isolation, job isolation, no secrets in
  source or logs.
- When something can be done deterministically, do not delegate it to the LLM.
- Never silently simplify a critical engineering feature; never claim a feature
  works unless it has been tested.

## Quality priorities

1 correct geometry · 2 correct dimensions · 3 correct views · 4 correct
annotations · 5 determinism · 6 QA · 7 traceability · 8 reliability ·
9 maintainability · 10 UX · 11 AI assistance.

## Development methodology

Build incrementally: skeleton → schemas → geometry pipeline → frontend →
backend → planner → compiler → SolidWorks worker → QA → end-to-end. After each
stage: run tests, fix, update docs. Current status and next milestone:
`docs/ROADMAP.md`.

## Commands

```bash
uv sync --all-packages                      # Python workspace (Python 3.12+)
uv run python scripts/generate_fixtures.py  # regenerate STEP/STL fixtures
uv run pytest                               # all Python tests
uv run uvicorn cad_api.main:create_app --factory --reload   # API on :8000
cd apps/frontend && npm install && npm run dev   # UI on :5173
cd apps/frontend && npm run typecheck && npm test && npm run build
```

## Documentation to keep current

README.md, docs/ARCHITECTURE.md, API.md, DEVELOPMENT.md, SOLIDWORKS_SETUP.md,
GEOMETRY.md, DRAWING_ENGINE.md, QA.md, DEPLOYMENT.md, THIRD_PARTY.md, ROADMAP.md.
