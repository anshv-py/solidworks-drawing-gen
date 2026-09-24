# CAD Drawing AI

Turns STEP/STP models into professional engineering drawings (PDF, DXF, SVG; SLDDRW/DWG
planned through a SolidWorks worker). Geometry comes from a deterministic engine (OCCT). The
drawing is planned by deterministic drafting rules and projected by OCCT's exact hidden-line
removal, then checked by deterministic QA. **No LLM is used and no paid service is required.**
Nothing is invented: every number on the sheet is traceable to the CAD geometry.

> **Status: milestones 1-2 done.** Upload → OCCT analysis → GeometryIR → features → 3D preview →
> **drawing generation** (views, dimensions, hole callouts, center marks, title block) → QA →
> PDF/DXF/SVG download. Sections/detail views and the SolidWorks worker (SLDDRW/DWG) are next.
> See [docs/ROADMAP.md](docs/ROADMAP.md).

![Generated drawing of the flange test part](docs/images/drawing-flange.png)

## What works (tested)

| Capability | Notes |
|---|---|
| STEP import (AP203/214/242 geometry) | units converted to mm (mm/m/inch verified), BRepCheck validity |
| STL import (binary + ASCII) | bbox, area, volume/centroid if watertight; all values flagged *inferred* |
| Properties | bounding box, volume, surface area, centroid, principal axes, symmetry-plane candidates |
| Topology | solids/shells/faces/edges/vertices with adjacency and edge convexity |
| Features (STEP) | holes (through/blind, counterbore, countersink), bosses/external Ø, slots, pockets, fillets/rounds, planar & conical chamfers, circular/rectangular/linear hole patterns |
| Stable IDs | content-hash IDs for faces/edges/features, identical across re-analysis |
| API | upload (validated, size-limited, sniffed), async analysis jobs with progress, GeometryIR, preview mesh |
| Drawing generation | deterministic plan (views, dimension candidates from GeometryIR, redundancy removal), ISO/ASME, first/third angle, A0-A4, ISO 5455 scale, OCCT hidden-line removal, hole callouts / PCD / radii / chamfers, center marks & centerlines, title block with UNSPECIFIED engineering data |
| QA | 18 deterministic checks incl. OCCT-vs-GeometryIR cross-checks; repair loop (≤ 3); critical issues block export |
| Exports | PDF, DXF (real DIMENSION entities), SVG, PNG preview - labelled "not produced by SolidWorks"; DWG/SLDDRW → 501 until the SolidWorks worker exists |
| UI | upload, progress, geometry summary, feature table, Three.js preview, drawing settings, generate, drawing preview, QA report, downloads, regenerate |

## Quick start

```bash
uv sync --all-packages                                  # Python 3.12+ workspace
uv run pytest                                           # 100+ tests incl. end-to-end
uv run uvicorn cad_api.main:create_app --factory --reload   # API :8000
cd apps/frontend && npm install && npm run dev          # UI  :5173
```
Test models: `examples/models/*.step` (regenerate with `uv run python scripts/generate_fixtures.py`).

Docker: `cp .env.example .env` (set `POSTGRES_PASSWORD`), then `docker compose up --build`.
The UI is on :8080.

## Repository layout

```
apps/api                 FastAPI (cad_api)            apps/frontend   React+TS+Vite+Tailwind+Three.js
apps/solidworks-worker   Windows worker (contract only, milestone 6)
services/geometry        OCCT pipeline (geometry_service)
services/drawing-planner candidates + deterministic plan   services/drawing-compiler  sheet layout
services/drawing-executor OCCT HLR + ezdxf + matplotlib     services/drawing-qa        QA + repairs
packages/geometry-schema GeometryIR   packages/drawing-schema DrawingPlan   packages/shared-types
infrastructure/          Dockerfiles, compose support      tests/  geometry, schemas, api, integration, meta
examples/                models, reference drawings, GeometryIR, plans   references/  official-source index
.claude/skills/          5 Claude skills               CLAUDE.md  project instructions
```

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [API](docs/API.md) · [Development](docs/DEVELOPMENT.md) ·
[Geometry](docs/GEOMETRY.md) · [Drawing engine](docs/DRAWING_ENGINE.md) · [QA](docs/QA.md) ·
[SolidWorks setup](docs/SOLIDWORKS_SETUP.md) · [Deployment](docs/DEPLOYMENT.md) ·
[Third-party licences](docs/THIRD_PARTY.md) · [Roadmap](docs/ROADMAP.md)

## Engineering rules

Never invent geometry, dimensions, material, tolerances, GD&T, datums, finish,
treatment, inspection or process data. A CAD model yields a **geometry drawing**.
A **manufacturing drawing** requires information supplied by the user. Mock
SolidWorks output is always labelled `MOCK`.

## Licence

See [LICENSE](LICENSE) and [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).
