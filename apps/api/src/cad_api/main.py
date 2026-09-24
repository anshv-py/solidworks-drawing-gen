"""Application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cad_api.config import Settings, get_settings
from cad_api.db import Database
from cad_api.errors import install_handlers
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
        from pathlib import Path

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
    install_handlers(app)
    app.include_router(models.router)
    app.include_router(jobs.router)
    app.include_router(drawings.router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "solidworks_mode": settings.solidworks_mode}

    return app

