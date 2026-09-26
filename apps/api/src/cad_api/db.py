"""Persistence: SQLAlchemy 2.0 ORM (PostgreSQL in deployment, SQLite for dev/tests)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def _now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class ModelStatus(StrEnum):
    UPLOADED = "UPLOADED"
    ANALYZING = "ANALYZING"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"


class JobKind(StrEnum):
    ANALYZE = "ANALYZE"
    DRAWING = "DRAWING"


class JobState(StrEnum):
    QUEUED = "QUEUED"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    GENERATING = "GENERATING"
    VALIDATING = "VALIDATING"
    EXPORTING = "EXPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


TERMINAL_STATES = {JobState.COMPLETED, JobState.FAILED}


class CadModel(Base):
    __tablename__ = "cad_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(8))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default=ModelStatus.UPLOADED)
    feature_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # the version this upload revises (EX 2: a new CAD version regenerates the previous version's drawing)
    previous_model_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    model_id: Mapped[str] = mapped_column(ForeignKey("cad_models.id"), index=True)
    state: Mapped[str] = mapped_column(String(16), default=JobState.QUEUED)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Database:
    def __init__(self, url: str) -> None:
        kwargs: dict = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        self.engine: Engine = create_engine(url, pool_pre_ping=True, **kwargs)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        # Schema bootstrap; Alembic migrations are planned before production. Columns added since the first
        # release are added to existing tables here (nullable, so no data is touched).
        Base.metadata.create_all(self.engine)
        from sqlalchemy import inspect, text

        added = {"cad_models": {"previous_model_id": "VARCHAR(36)"}}
        insp = inspect(self.engine)
        with self.engine.begin() as conn:
            for table, cols in added.items():
                have = {c["name"] for c in insp.get_columns(table)}
                for col, sql_type in cols.items():
                    if col not in have:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {sql_type}"))

    def session(self) -> Iterator[Session]:
        with self.sessions() as s:
            yield s
