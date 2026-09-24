# CAD Drawing AI API + geometry service (OCCT runs in subprocesses of this image).
FROM python:3.12-slim-bookworm AS base
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

RUN useradd --system --uid 10001 --home /app cadai && mkdir -p /data && chown cadai /data
USER cadai
# /data is the only writable path for the non-root user: storage and the standalone SQLite DB live
# there (docker compose overrides CADAI_DATABASE_URL with Postgres)
ENV PATH="/app/.venv/bin:$PATH" CADAI_STORAGE_DIR=/data/storage CADAI_DATABASE_URL=sqlite:////data/cadai.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
CMD ["uvicorn", "cad_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
