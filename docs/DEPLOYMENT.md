# Deployment

## Linux stack (docker compose)
`postgres`, `redis` (reserved), `api` (FastAPI + OCCT subprocesses), `frontend` (nginx serving the
built SPA and proxying `/api`). Set secrets via `.env` / a secret store; never bake them into images.

```bash
cp .env.example .env   # set POSTGRES_PASSWORD
docker compose up --build   # UI http://localhost:8080, API http://localhost:8000
```

Verification status (Docker 28.1 on Windows, 2026-09-25): both images built (`api.Dockerfile`
with the `libgl1` step, `frontend.Dockerfile`). The API image started on its own (health OK) and
ran a full upload → OCCT analysis → drawing job through the API (flange, scale 1:1.5, default
datums/GD&T, QA passed, PDF/DXF/SVG). `docker compose up --build` came up healthy: postgres,
api (on Postgres), and nginx serving the SPA and proxying `/api`.

Notes:
- The image's default database is SQLite on the `/data` volume (`CADAI_DATABASE_URL=sqlite:////data/cadai.db`);
  compose overrides it with Postgres. `/data` is the only path the non-root user can write.
- Host ports 8000 (API) and 8080 (UI) must be free; change the `ports:` mappings if they are taken.

## Render (single web service)
`render.yaml` is a Render Blueprint: one Docker web service built from
`infrastructure/docker/app.Dockerfile` (the API also serves the built UI at `/`, so one URL and no
CORS), with a 10 GB persistent disk at `/data` for uploads, drawings and the SQLite database.

1. Render Dashboard → **New → Blueprint** → connect the GitHub repo and select the branch.
2. Enter a value for `CADAI_ACCESS_PASSWORD` when asked. The whole site then asks for
   user `cadai` + that password (HTTP Basic). `/api/health` stays open for Render's health check.
3. Deploy. The first build takes several minutes (OCCT/VTK wheels, image ~3.6 GB).

Sizing: a drawing job peaked at ~0.5 GB RAM on the example parts and on a sheet-metal
part (measured with `docker stats`, one job at a time). Use at least the `1c-2g` plan: 512 MB
plans, including `free`, run out of memory. A persistent disk also needs a paid plan.
`CADAI_JOB_WORKERS=1` keeps one job in memory at a time.

Verification status (2026-09-25): the API code paths (login gate, UI serving, URL
conversion) are covered by `tests/api/test_hosting.py`. `app.Dockerfile` combines the two verified
images' steps, but it has **not been built yet**: the build host's disk filled up. Build it once
locally or watch the first Render build log.

Notes:
- The disk ties the service to one instance (no horizontal scaling, and a short downtime on
  each deploy). To scale out, add a Render Postgres database and set `CADAI_DATABASE_URL` to its
  connection string (`postgres://` / `postgresql://` URLs are converted to the psycopg driver).
  Artifacts would then need shared object storage (open item below).
- Settings: `CADAI_FRONTEND_DIR` (set in the image), `CADAI_ACCESS_USER` (default `cadai`),
  `CADAI_ACCESS_PASSWORD` (unset = no login, e.g. local development).

## Production checklist (open)
- Alembic migrations (M1 uses `create_all`)
- Redis/RQ job runner for multi-instance API; SSE progress
- Per-user authentication (OIDC) behind `get_principal` (hosted deployments have a shared password)
- Object storage for artifacts; retention policy for uploads
- Reverse-proxy upload limit = `CADAI_MAX_UPLOAD_MB`
- Image size (~3.6 GB with VTK): evaluate `cadquery-ocp-novtk`
- Windows worker packaging as a service (milestone 6)
