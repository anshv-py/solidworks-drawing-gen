"""Application factory."""

from __future__ import annotations

import base64
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from cad_api.config import Settings, get_settings
from cad_api.db import Database
from cad_api.errors import NotFound, install_handlers
from cad_api.logging_config import configure_logging
from cad_api.routers import drawings, jobs, models
from cad_api.services.jobs import JobRunner, LocalProcessRunner
from cad_api.services.storage import Storage


def create_app(settings: Settings | None = None, runner: JobRunner | None = None) -> FastAPI:
    """Build the app. Run with: ``uvicorn cad_api.main:create_app --factory``."""
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.runner.shutdown()

    app = FastAPI(title="CAD Drawing AI API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    if settings.database_url.startswith("sqlite:///"):
        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    app.state.db = Database(settings.database_url)
    app.state.db.create_all()
    app.state.storage = Storage(settings.storage_dir)
    app.state.runner = runner or LocalProcessRunner(settings, app.state.db, app.state.storage)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    if settings.access_password is not None:
        _install_basic_auth(app, settings.access_user, settings.access_password.get_secret_value())
    install_handlers(app)
    app.include_router(models.router)
    app.include_router(jobs.router)
    app.include_router(drawings.router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "solidworks_mode": settings.solidworks_mode}

    if settings.frontend_dir is not None:
        _serve_frontend(app, settings.frontend_dir)
    return app


def _install_basic_auth(app: FastAPI, user: str, password: str) -> None:
    """Shared-password gate (HTTP Basic) for hosted deployments; the health check stays open."""
    expected = base64.b64encode(f"{user}:{password}".encode()).decode()

    @app.middleware("http")
    async def basic_auth(request: Request, call_next):
        if request.url.path == "/api/health" or request.method == "OPTIONS":
            return await call_next(request)
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "basic" and secrets.compare_digest(token.strip(), expected):
            return await call_next(request)
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="CAD Drawing AI"'})


def _serve_frontend(app: FastAPI, root: Path) -> None:
    """The built single-page app at /, with index.html for client-side routes."""
    root = root.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise NotFound(f"no API route /{path}")
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root):  # no path traversal out of root
            return FileResponse(file)
        return FileResponse(index)

