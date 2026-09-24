# CI/CD

CI (GitHub Actions `.github/workflows/ci.yml`):
1. Python: `uv sync --all-packages` → `uv run pytest`.
2. Frontend: `npm ci` → `npm run typecheck` → `npm test` → `npm run build`.
3. (Later) Windows job for the worker: `dotnet build` + tests with mock executor.
CD: build images from `infrastructure/docker/*.Dockerfile`; worker shipped as a
signed Windows service package.
