"""HTTP response/request models (API surface, distinct from ORM rows)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from drawing_schema import DrawingPlan


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    format: str
    size_bytes: int
    sha256: str
    status: str
    feature_count: int | None
    created_at: datetime


class JobError(BaseModel):
    code: str
    message: str


class JobOut(BaseModel):
    id: str
    kind: str
    model_id: str
    state: str
    progress: float
    message: str | None
    error: JobError | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_row(cls, job) -> "JobOut":
        return cls(
            id=job.id,
            kind=job.kind,
            model_id=job.model_id,
            state=job.state,
            progress=job.progress,
            message=job.message,
            error=JobError(code=job.error_code, message=job.error_message or "") if job.error_code else None,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )


class AnalyzeAccepted(BaseModel):
    job_id: str
    job: JobOut


class DrawingDefaults(BaseModel):
    """Product defaults for the drawing-settings UI (from the DrawingPlan schema)."""

    plan: DrawingPlan
    options: dict[str, list[str]]
