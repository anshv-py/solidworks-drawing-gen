# Single-service image for hosted deployments (Render): the API also serves the built UI at /.
# The docker compose stack keeps two images (api.Dockerfile + frontend.Dockerfile behind nginx).

FROM node:22-bookworm-slim AS frontend
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
WORKDIR /src
COPY apps/frontend/package.json apps/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/frontend ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
# Runtime libraries needed by the OCCT/VTK wheels (cadquery-ocp).
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglu1-mesa libxrender1 libxext6 libx11-6 libgomp1 \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.8.17

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY services ./services
COPY apps/api ./apps/api
RUN uv sync --frozen --all-packages --no-dev
COPY --from=frontend /src/dist ./frontend

RUN useradd --system --uid 10001 --home /app cadai && mkdir -p /data && chown cadai /data
# a host-mounted disk at /data may arrive root-owned: the entrypoint fixes that, then drops to cadai
COPY infrastructure/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/$//' /usr/local/bin/entrypoint.sh && chmod 755 /usr/local/bin/entrypoint.sh
# /data is the persistent disk: uploads, drawings and the SQLite database (set CADAI_DATABASE_URL
# to a Postgres URL to use Postgres instead)
ENV PATH="/app/.venv/bin:$PATH" CADAI_STORAGE_DIR=/data/storage CADAI_DATABASE_URL=sqlite:////data/cadai.db \
    CADAI_FRONTEND_DIR=/app/frontend
EXPOSE 8000
# hosts such as Render pass the port in $PORT
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn cad_api.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
