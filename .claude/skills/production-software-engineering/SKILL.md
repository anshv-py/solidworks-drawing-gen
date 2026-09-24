---
name: production-software-engineering
description: Production engineering conventions for the CAD Drawing AI codebase. Activate when writing or reviewing application code, tests, configuration or infrastructure - Python 3.12/FastAPI/Pydantic v2/SQLAlchemy 2/PostgreSQL/Redis job queues, React/TypeScript/Vite/Tailwind/Three.js frontend, C#/.NET worker plumbing (not SolidWorks calls), REST/SSE API design, background jobs and progress reporting, Docker/compose, Windows worker deployment, logging/observability, secrets, upload security, error handling, module boundaries, and CI/CD. Do NOT use for CAD/drawing domain decisions (cad-engineering-automation), OCCT algorithms (occt-geometry-step), SolidWorks API usage (solidworks-api-automation) or QA rules (cad-drawing-qa).
---

# Production Software Engineering

Maintainable, testable, secure production architecture - not a prototype.

## Repository layout (monorepo, uv workspace + npm)

```
apps/api                FastAPI app (package cad_api) - HTTP, persistence, jobs
apps/frontend           React + TS + Vite + Tailwind + Three.js
apps/solidworks-worker  C#/.NET Windows worker (pull-based job leasing)
services/geometry       OCCT pipeline (package geometry_service) - runs in a subprocess
services/drawing-*      planner / compiler / qa packages
packages/*-schema       Pydantic models = contracts (+ exported JSON Schema for TS/C#)
packages/shared-types   shared enums/value types
```

Dependency direction: `apps → services → packages`. Packages never import
services; `cad_api` never imports `OCP` (geometry runs out-of-process).

## Python rules
- Python ≥ 3.12, type hints everywhere, `from __future__ import annotations` not needed.
- Pydantic v2 models are the contracts; `model_config = ConfigDict(extra="forbid", frozen=True)` for IR/plan types.
- Settings via `pydantic-settings` (`CADAI_` env prefix); no secrets in code or logs.
- SQLAlchemy 2.0 typed ORM (`Mapped[...]`); one session per request via dependency.
- No business logic in routers - routers → service layer → repositories.
- Errors: domain exceptions → mapped to RFC 9457 problem+json in one handler.
- Logging: structured JSON (`logging` + formatter), request id / job id in every record; never log file contents or API keys.

## Jobs
- States: `QUEUED → ANALYZING → PLANNING → GENERATING → VALIDATING → EXPORTING → COMPLETED | FAILED`.
- Job record holds `stage`, `progress` (0-100), `message`, `error{code,message}`, timestamps.
- `JobRunner` protocol: `LocalProcessRunner` (dev/tests: thread pool + subprocess) and a Redis-backed runner (RQ) for deployment - same interface.
- CAD parsing runs in a **subprocess** with timeout + RLIMIT_AS; progress is streamed as JSON lines on stdout.
- Frontend receives progress by polling `GET /api/jobs/{id}` (SSE endpoint planned).

## Upload security
Allowlisted extensions (`.step .stp .stl`), content sniffing (ISO-10303-21 header;
STL binary size formula / ASCII `solid…facet`), size limit, server-generated
storage names (UUID) under a configured root, `resolve()` + `is_relative_to`
check on every path, original filename only as sanitized metadata.

## Frontend rules
- Strict TS; API types generated from JSON Schema (`npm run gen:types`), not hand-copied.
- Components small; data fetching in hooks (`useJob`, `useModel`); Three.js scene in one component with disposal on unmount.
- Tailwind utility classes; no inline style objects except canvas sizing.

## Testing
- `pytest` for Python (unit + API via `httpx`/`TestClient` + geometry with generated STEP fixtures); `vitest` + `tsc --noEmit` + `vite build` for the frontend.
- Fixtures are generated deterministically by `scripts/generate_fixtures.py`; expected values are the construction parameters.
- Never mark a feature done without a test that exercises it.

## References
- `references/api-conventions.md`
- `references/security-checklist.md`
- `references/ci-cd.md`
- `examples/router-service-pattern.py`
