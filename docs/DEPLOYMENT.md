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

## Production checklist (open)
- Alembic migrations (M1 uses `create_all`)
- Redis/RQ job runner for multi-instance API; SSE progress
- Authentication (OIDC) behind `get_principal`
- Object storage for artifacts; retention policy for uploads
- Reverse-proxy upload limit = `CADAI_MAX_UPLOAD_MB`
- Image size (~3.6 GB with VTK): evaluate `cadquery-ocp-novtk`
- Windows worker packaging as a service (milestone 6)
