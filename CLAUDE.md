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
| Deterministic planner (no LLM; optional LLM hook `CADAI_LLM_BACKEND`, default `none`) | planning: views, dimension selection, redundancy - output validated against the DrawingPlan schema |
| OCCT | geometry truth |
| Deterministic algorithms | measurements, feature recognition, dimension candidates, validation |
| Open-source executor (OCCT HLR + ezdxf) | PDF/DXF/SVG drawings today, labelled "not produced by SolidWorks" |
| SolidWorks (Windows worker, planned) | authoritative native drawings (SLDDRW) and DWG |
| QA system | drawing validation |

No LLM is required: drafting decisions are deterministic rules. The planner emits a typed
**DrawingPlan**; a deterministic compiler turns it into a CompiledDrawing (sheet ops) that an
executor (OCCT/ezdxf today, SolidWorks later) draws.

## Workflow

upload → validation → geometry extraction → feature recognition → GeometryIR →
user drawing settings → DrawingPlan (deterministic planner) → plan validation →
drawing compiler → executor (OCCT HLR + ezdxf; SolidWorks worker later for SLDDRW/DWG) →
deterministic QA → repair (max `QA_MAX_RETRIES`, default 3) → PDF/DXF/SVG.

Defaults: standard **ISO**, projection **FIRST ANGLE**, sheet **A3 LANDSCAPE**, units **mm**.

## Primary drawing rule set (owner decision, 2026-09-26)

`services/drawing-planner/src/drawing_planner/rules/` holds the owner's two rule documents
(`manufacturing_drawing_rules.md` = RULES, `manufacturing_drawing_reference_examples.md` = EX, kept
verbatim) and their executable form `drawing_rules.yaml`. It is the default configuration of every
upload (`DrawingSettings.view_selection=RULES`):
- views: the fewest orthographic views (RULES 1.1), an isometric only when a RULES 1.2 trigger fires;
  section / detail / auxiliary / break triggers are detected and reported (drawn in later phases)
- functional roles (mounting face, bearing bore / seat, clearance / dowel / tapped hole ...) are
  inferred from geometry, always reported as "assumed role: X - confirm or override", overridable per
  feature id (`feature_roles`); the role's fits (ISO 286 table), GD&T and finish from the rule set apply
  with `source=DEFAULT` (incl. derived thread callouts of assumed tapped holes: blind thread depth =
  drill depth − 3 × pitch, owner decision 2026-09-26)
- compliance gate (EX 1): every drawing gets `compliance.json`; failing hard blockers stamp the sheet
  NOT FOR MANUFACTURE and make `POST /api/drawings/{id}/release` refuse - generation and downloads are
  never blocked
Change rules in the YAML (with the RULES / EX reference), not in code. Phases: `docs/ROADMAP.md`.

## Never invent

geometry · numerical dimensions · material · general tolerance · GD&T ·
datum scheme · surface finish · heat treatment · coating · inspection
requirements · manufacturing process. Use only GeometryIR and explicit user
metadata; otherwise mark `UNSPECIFIED`. Sole exception (owner's decisions): the default datum
scheme + GD&T of `drawing_planner/gdt_defaults.py`, derived from a declared ISO 2768-mK, and the
primary rule set's defaults (general tolerance, default finish, and the fits / GD&T / finish of each
feature's *assumed* functional role), all labelled `source=DEFAULT`, reported in the compliance
report, applied only when the user supplied none (`default_gdt`, switchable). Material, part number,
revision, heat treatment, coating and inspection are still never invented. Distinguish a **GEOMETRY DRAWING**
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
- Never invent APIs (SolidWorks, OCCT, Hugging Face transformers). Consult official docs; if a
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
