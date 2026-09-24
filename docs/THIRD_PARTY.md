# Third-party software and licences (reviewed 2026-09-24)

| Component | Use | Licence | Notes |
|---|---|---|---|
| Open CASCADE Technology 8 | geometry kernel | LGPL-2.1 + OCCT exception | dynamically linked via wheel; do not statically link/modify without review |
| cadquery-ocp 8.0.1 | Python bindings to OCCT | Apache-2.0 | pulls VTK |
| VTK 9.6 | dependency of cadquery-ocp | BSD-3-Clause | unused by our code |
| FastAPI, Starlette, Pydantic, pydantic-settings, SQLAlchemy, Uvicorn | backend | MIT / BSD / MIT | |
| psycopg 3 | PostgreSQL driver | LGPL-3.0 | dynamic use as a library |
| NumPy | numerics | BSD-3-Clause | |
| ezdxf 1.4 | DXF writing + DXF rendering (drawing add-on) | MIT | |
| Liberation Sans (font) | drawing text (referenced by name; used if installed, not redistributed) | SIL OFL 1.1 | ezdxf falls back to another installed font |
| matplotlib 3.11 | PDF/SVG/PNG rendering backend | matplotlib licence (PSF-based, BSD-compatible) | |
| React, Vite, Tailwind CSS, three.js, Vitest, json-schema-to-typescript | frontend | MIT | |
| Playwright (dev only) | browser e2e | Apache-2.0 | |
| SolidWorks API | drawing generation (planned) | proprietary (Dassault Systèmes) | requires licensed seats on worker hosts |
| (optional) DeepSeek-V4-Pro / Hugging Face transformers | LLM hook - **not used** (`CADAI_LLM_BACKEND=none`) | MIT / Apache-2.0 | see DRAWING_ENGINE.md |

Rejected: LibreDWG (GPL-3.0, incompatible with a proprietary product) and PyMuPDF (AGPL-3.0).

## Reference repositories (not used as dependencies)
| Repo | Licence | Decision |
|---|---|---|
| U-C4N/Autocad-MCP | MIT | ideas only; no code copied |
| eyfel/mcp-server-solidworks | **AGPL-3.0** (+CLA dual licensing) | **no code copying or linking**; architectural observations only |

Details: `references/architecture/reference-repos-review.md`.
