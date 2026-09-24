# Architecture decisions (milestone 1)

| # | Decision | Alternatives | Reason |
|---|---|---|---|
| 1 | Monorepo at repo root (not nested `cad-drawing-ai/`) | nested folder | the git repository *is* the product; nesting adds a path level with no benefit |
| 2 | uv workspace; each contract/service is its own Python package | single package | enforces dependency direction (apps → services → packages); API cannot import OCCT |
| 3 | OCCT via `cadquery-ocp` wheels | pythonocc-core (conda only), C++ service | pip-installable, Apache-2.0 bindings, tracks OCCT 8 |
| 4 | Geometry analysis in a subprocess per job | in-process | malformed CAD can crash native code; enables timeout + memory limit |
| 5 | Job runner interface; thread-pool runner now, RQ later | Celery now | RQ is simpler (Redis only); Windows worker uses HTTP leasing, not the Python queue |
| 6 | Stable content-hash IDs for faces/edges/features | OCCT traversal indices | survive re-analysis; referenced by DrawingPlan/QA |
| 7 | GeometryIR/DrawingPlan as Pydantic → JSON Schema → TS types | hand-written TS | single source of truth, drift checked in CI |
| 8 | Preview mesh = JSON with per-face groups | glTF | per-face highlighting of recognized features with minimal code; glTF/binary later if size demands |
| 9 | Z-up model frame in GeometryIR/preview | Y-up | CAD convention; the SolidWorks view mapping (Y-up in SW) must be specified in the compiler milestone |
