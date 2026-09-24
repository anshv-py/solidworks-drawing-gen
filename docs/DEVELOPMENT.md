# Development

## Prerequisites
- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (Linux/macOS x86_64/arm64; OCCT wheels via `cadquery-ocp`)
- Node 22+
- Linux containers need `libgl1` (the OCCT wheel links libGL; verified - import fails without it)

## Setup & run
```bash
uv sync --all-packages
uv run python scripts/generate_fixtures.py          # examples/models (+ manifest.json)
uv run uvicorn cad_api.main:create_app --factory --reload
cd apps/frontend && npm install && npm run dev      # proxies /api to :8000
```

## Tests
```bash
uv run pytest                    # all Python tests (geometry, schemas, API, integration, skills)
uv run pytest -m "not slow"      # skip the full HTTP pipeline over all fixtures
cd apps/frontend
npm run typecheck && npm test && npm run build
npm run e2e -- ../../examples/models/flange.step /tmp/shot.png           # upload + 3D preview
npm run e2e:drawing -- ../../examples/models/flange.step /tmp/draw.png  # + generate drawing, QA, PDF
```
Playwright is pinned to 1.56.1 to match the preinstalled Chromium in the dev container;
set `CHROMIUM_PATH` if your browser lives elsewhere.

## Contracts
Edit Pydantic models, then:
```bash
uv run python scripts/export_schemas.py && (cd apps/frontend && npm run gen:types)
```
CI fails if exported schemas or generated TS types are stale.

## Conventions
See `.claude/skills/production-software-engineering/SKILL.md`. Geometry code:
`.claude/skills/occt-geometry-step/SKILL.md` (only OCP calls verified in
`references/ocp-api-verified.md`).
