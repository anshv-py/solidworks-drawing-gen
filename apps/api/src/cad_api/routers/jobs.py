from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from cad_api.db import Job, JobKind
from cad_api.dependencies import Principal, get_principal, get_session
from cad_api.errors import Conflict, NotFound, NotImplementedYet
from cad_api.schemas import JobOut

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

DOWNLOAD_FORMATS = ("dwg", "pdf", "dxf", "slddrw")


def _get_job(session: Session, job_id: str, principal: Principal) -> Job:
    job = session.get(Job, job_id)
    if job is None or job.owner_id != principal.id:
        raise NotFound(f"job {job_id} not found")
    return job


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, session: Session = Depends(get_session), principal: Principal = Depends(get_principal)):
    return JobOut.from_row(_get_job(session, job_id, principal))


def _drawing_job(session: Session, job_id: str, principal: Principal) -> Job:
    job = _get_job(session, job_id, principal)
    if job.kind != JobKind.DRAWING:
        raise Conflict("this job is not a drawing job; it has no drawing artifacts", code="NOT_A_DRAWING_JOB")
    raise NotImplementedYet("drawing artifacts are produced from milestone 3 onwards")


@router.get("/{job_id}/preview")
def get_drawing_preview(
    job_id: str, session: Session = Depends(get_session), principal: Principal = Depends(get_principal)
):
    _drawing_job(session, job_id, principal)


@router.get("/{job_id}/download/{fmt}")
def download(
    job_id: str, fmt: str, session: Session = Depends(get_session), principal: Principal = Depends(get_principal)
):
    if fmt not in DOWNLOAD_FORMATS:
        raise NotFound(f"unknown format {fmt!r}; expected one of {DOWNLOAD_FORMATS}")
    _drawing_job(session, job_id, principal)
