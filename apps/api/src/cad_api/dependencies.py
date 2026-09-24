"""Dependency wiring. ``get_principal`` is the single hook for authentication."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.orm import Session

from cad_api.config import Settings
from cad_api.db import Database
from cad_api.services.jobs import JobRunner
from cad_api.services.storage import Storage


@dataclass(frozen=True)
class Principal:
    id: str


def get_principal() -> Principal:
    # Authentication-ready: replace with token validation; handlers already scope by owner.
    return Principal(id="anonymous")


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


def get_runner(request: Request) -> JobRunner:
    return request.app.state.runner


def get_session(request: Request) -> Iterator[Session]:
    db: Database = request.app.state.db
    yield from db.session()
