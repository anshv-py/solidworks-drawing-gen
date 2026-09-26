from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from cad_api.config import Settings
from cad_api.db import CadModel, Job, JobKind, JobState, ModelStatus, TERMINAL_STATES
from cad_api.dependencies import (
    Principal,
    get_principal,
    get_runner,
    get_session,
    get_settings_dep,
    get_storage,
)
from cad_api.errors import Conflict, FileTooLarge, NotFound, UnsupportedFile
from cad_api.schemas import AnalyzeAccepted, JobOut, ModelOut
from cad_api.services.jobs import JobRunner
from cad_api.services.sniff import format_from_extension, sanitize_filename, sniff
from cad_api.services.storage import Storage, sha256_of

router = APIRouter(prefix="/api/models", tags=["models"])


def _get_model(session: Session, model_id: str, principal: Principal) -> CadModel:
    model = session.get(CadModel, model_id)
    if model is None or model.owner_id != principal.id:
        raise NotFound(f"model {model_id} not found")
    return model


@router.post("/upload", status_code=status.HTTP_201_CREATED, response_model=ModelOut)
def upload_model(
    file: UploadFile = File(...),
    previous_model_id: str | None = Form(default=None),
    content_length: int | None = Header(default=None),
    settings: Settings = Depends(get_settings_dep),
    storage: Storage = Depends(get_storage),
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> CadModel:
    if content_length is not None and content_length > settings.max_upload_bytes + 64 * 1024:
        raise FileTooLarge(f"file exceeds the {settings.max_upload_mb} MB limit")
    if previous_model_id is not None:
        _get_model(session, previous_model_id, principal)  # a version of the caller's own part
    filename = sanitize_filename(file.filename)
    declared = format_from_extension(filename)
    if declared is None:
        raise UnsupportedFile("only .step, .stp and .stl files are accepted")
    tmp = storage.receive(file.file, settings.max_upload_bytes)
    try:
        if tmp.stat().st_size == 0:
            raise UnsupportedFile("the file is empty", code="INVALID_CAD_CONTENT")
        detected = sniff(tmp)
        if detected is None:
            raise UnsupportedFile("file content is not a STEP (ISO 10303-21) or STL file", code="INVALID_CAD_CONTENT")
        if detected != declared:
            raise UnsupportedFile(
                f"file extension says {declared.value} but content is {detected.value}", code="EXTENSION_MISMATCH"
            )
        model = CadModel(
            owner_id=principal.id,
            original_filename=filename,
            format=detected.value,
            size_bytes=tmp.stat().st_size,
            sha256=sha256_of(tmp),
            status=ModelStatus.UPLOADED,
            previous_model_id=previous_model_id,
        )
        session.add(model)
        session.flush()
        storage.commit_upload(tmp, model.id, ".step" if detected.value == "STEP" else ".stl")
        session.commit()
        return model
    finally:
        tmp.unlink(missing_ok=True)


@router.get("/{model_id}", response_model=ModelOut)
def get_model(
    model_id: str, session: Session = Depends(get_session), principal: Principal = Depends(get_principal)
) -> CadModel:
    return _get_model(session, model_id, principal)


@router.get("/{model_id}/drawings", response_model=list[JobOut])
def model_drawings(
    model_id: str, session: Session = Depends(get_session), principal: Principal = Depends(get_principal)
) -> list[JobOut]:
    """Drawing jobs of a model, newest first (a new CAD version's drawing is started automatically)."""
    model = _get_model(session, model_id, principal)
    jobs = session.scalars(select(Job).where(Job.model_id == model.id, Job.kind == JobKind.DRAWING)
                           .order_by(Job.created_at.desc())).all()
    return [JobOut.from_row(j) for j in jobs]


@router.post("/{model_id}/analyze", status_code=status.HTTP_202_ACCEPTED, response_model=AnalyzeAccepted)
def analyze_model(
    model_id: str,
    session: Session = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
    principal: Principal = Depends(get_principal),
) -> AnalyzeAccepted:
    model = _get_model(session, model_id, principal)
    running = session.scalars(
        select(Job).where(Job.model_id == model.id, Job.kind == JobKind.ANALYZE, Job.state.not_in(TERMINAL_STATES))
    ).first()
    if running is not None:
        return AnalyzeAccepted(job_id=running.id, job=JobOut.from_row(running))
    job = Job(owner_id=principal.id, kind=JobKind.ANALYZE, model_id=model.id, state=JobState.QUEUED,
              message="Queued")
    session.add(job)
    session.commit()
    runner.submit(job.id)
    return AnalyzeAccepted(job_id=job.id, job=JobOut.from_row(job))


def _artifact(storage: Storage, model: CadModel, name: str):
    if model.status != ModelStatus.ANALYZED:
        raise Conflict(f"model is {model.status}; analyze it first", code="MODEL_NOT_ANALYZED")
    path = storage.path("models", model.id, name)
    if not path.exists():
        raise NotFound(f"{name} not available for this model")
    return path


@router.get("/{model_id}/geometry", summary="GeometryIR for an analyzed model")
def get_geometry(
    model_id: str,
    session: Session = Depends(get_session),
    storage: Storage = Depends(get_storage),
    principal: Principal = Depends(get_principal),
) -> Response:
    path = _artifact(storage, _get_model(session, model_id, principal), "geometry_ir.json")
    return FileResponse(path, media_type="application/json")


@router.get("/{model_id}/preview-mesh", summary="Tessellated preview (per-face triangle groups)")
def get_preview_mesh(
    model_id: str,
    session: Session = Depends(get_session),
    storage: Storage = Depends(get_storage),
    principal: Principal = Depends(get_principal),
) -> Response:
    path = _artifact(storage, _get_model(session, model_id, principal), "preview_mesh.json")
    return FileResponse(path, media_type="application/json")

