"""HTTP response/request models (API surface, distinct from ORM rows)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from drawing_schema.qa import QaReport
from drawing_schema.settings import DrawingSettings


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
    """Product defaults for the drawing-settings UI (from the DrawingSettings schema)."""

    settings: DrawingSettings
    options: dict[str, list[str]]


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    settings: DrawingSettings = DrawingSettings()


class RegenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: DrawingSettings | None = None


class DrawingAccepted(BaseModel):
    drawing_id: str
    job_id: str
    job: JobOut


class DrawingOut(BaseModel):
    id: str
    model_id: str
    job: JobOut
    settings: DrawingSettings
    passed: bool | None
    scale: str | None
    generator: str | None
    solidworks: bool = False
    downloads: list[str]
    unavailable_formats: dict[str, str]
    qa: QaReport | None


class AnnotationDimension(BaseModel):
    id: str
    text: str
    kind: str


class AnnotationFace(BaseModel):
    id: str
    normal: tuple[float, float, float] | None
    area: float
    centroid: tuple[float, float, float]


class AnnotationFeature(BaseModel):
    id: str
    type: str
    diameter: float | None = None


class AnnotationTargets(BaseModel):
    """Ids a user annotation may reference (all from GeometryIR / the deterministic plan)."""

    dimensions: list[AnnotationDimension]
    planar_faces: list[AnnotationFace]
    features: list[AnnotationFeature]
