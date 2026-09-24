from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from cad_api.db import Job, JobKind, JobState
from cad_api.dependencies import Principal, get_principal, get_session, get_storage
from cad_api.errors import Conflict, NotFound, NotImplementedYet
from cad_api.routers.drawings import FORMATS, UNAVAILABLE
from cad_api.schemas import JobOut
from cad_api.services.storage import Storage

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

MEDIA = {"pdf": "application/pdf", "dxf": "image/vnd.dxf", "svg": "image/svg+xml"}


def _get_job(session: Session, job_id: str, principal: Principal) -> Job:
    job = session.get(Job, job_id)
    if job is None or job.owner_id != principal.id:
        raise NotFound(f"job {job_id} not found")
    return job


def _drawing_job(session: Session, job_id: str, principal: Principal) -> Job:
    job = _get_job(session, job_id, principal)
    if job.kind != JobKind.DRAWING:
        raise Conflict("this job is not a drawing job; it has no drawing artifacts", code="NOT_A_DRAWING_JOB")
    return job


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, session: Session = Depends(get_session), principal: Principal = Depends(get_principal)):
    return JobOut.from_row(_get_job(session, job_id, principal))


@router.get("/{job_id}/preview", summary="PNG preview of the drawing sheet (also for QA-rejected drafts)")
def get_drawing_preview(job_id: str, session: Session = Depends(get_session), storage: Storage = Depends(get_storage),
                        principal: Principal = Depends(get_principal)):
    job = _drawing_job(session, job_id, principal)
    for name in ("preview.png", "preview_failed_qa.png"):
        p = storage.path("drawings", job.id, name)
        if p.exists():
            return FileResponse(p, media_type="image/png")
    raise Conflict("no preview yet", code="JOB_NOT_COMPLETE")


@router.get("/{job_id}/download/{fmt}")
def download(job_id: str, fmt: str, session: Session = Depends(get_session), storage: Storage = Depends(get_storage),
             principal: Principal = Depends(get_principal)):
    if fmt in UNAVAILABLE:
        _drawing_job(session, job_id, principal)
        raise NotImplementedYet(UNAVAILABLE[fmt], code="FORMAT_REQUIRES_SOLIDWORKS")
    if fmt not in FORMATS:
        raise NotFound(f"unknown format {fmt!r}; expected one of {sorted([*FORMATS, *UNAVAILABLE])}")
    job = _drawing_job(session, job_id, principal)
    if job.state == JobState.FAILED and job.error_code == "QA_FAILED":
        raise Conflict("the drawing failed QA; exports are blocked", code="QA_FAILED")
    p = storage.path("drawings", job.id, FORMATS[fmt])
    if job.state != JobState.COMPLETED or not p.exists():
        raise Conflict("the drawing is not complete", code="JOB_NOT_COMPLETE")
    return FileResponse(p, media_type=MEDIA[fmt], filename=f"drawing-{job.id[:8]}.{fmt}")
