# Deployment

## Linux stack (docker compose)
`postgres`, `redis` (reserved), `api` (FastAPI + OCCT subprocesses), `frontend` (nginx serving the
built SPA and proxying `/api`). Set secrets via `.env` / a secret store; never bake them into images.

```bash
cp .env.example .env   # set POSTGRES_PASSWORD
docker compose up --build   # UI http://localhost:8080, API http://localhost:8000
```

Verification status (sandbox, 2026-09-24): a variant of the API image *without* the
`libgl1` apt step was built and run. `/api/health` and uploads worked, but the analysis
subprocess failed with `libGL.so.1: cannot open shared object file`, which confirms that the
apt step is required. The committed Dockerfile, with that step, could not be built in the
sandbox because its egress policy blocks `deb.debian.org`. The frontend image and
`docker compose up` were not built there either. Validate them in CI or on a host with
Debian mirror access.

## Production checklist (open)
- Alembic migrations (M1 uses `create_all`)
- Redis/RQ job runner for multi-instance API; SSE progress
- Authentication (OIDC) behind `get_principal`
- Object storage for artifacts; retention policy for uploads
- Reverse-proxy upload limit = `CADAI_MAX_UPLOAD_MB`
- Image size (~3.6 GB with VTK): evaluate `cadquery-ocp-novtk`
- Windows worker packaging as a service (milestone 6)
