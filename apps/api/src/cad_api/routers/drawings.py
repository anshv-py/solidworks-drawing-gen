"""Drawing generation endpoints.

Drawings are produced by the open-source executor (OCCT hidden-line removal + ezdxf) after a
deterministic plan and deterministic QA. They are labelled as such and are never presented as
SolidWorks output. DWG and SLDDRW need the SolidWorks worker and return 501 until it exists.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from cad_api.db import CadModel, Job, JobKind, JobState, ModelStatus
from cad_api.dependencies import Principal, get_principal, get_runner, get_session, get_storage
from cad_api.errors import Conflict, NotFound
from cad_api.schemas import (
    DrawingAccepted,
    DrawingDefaults,
    DrawingOut,
    GenerateRequest,
    JobOut,
    RegenerateRequest,
)
from cad_api.services.jobs import JobRunner
from cad_api.services.storage import Storage
from drawing_schema import (
    DisplayStyle,
    DrawingKind,
    DrawingStandard,
    ProjectionMethod,
    SheetOrientation,
    SheetSize,
    ViewFrame,
    ViewOrientation,
)
from drawing_schema.qa import QaReport
from drawing_schema.settings import DrawingSettings

router = APIRouter(prefix="/api/drawings", tags=["drawings"])

FORMATS = {"pdf": "drawing.pdf", "dxf": "drawing.dxf", "svg": "drawing.svg"}
UNAVAILABLE = {
    "dwg": "DWG export requires the SolidWorks worker (not deployed); no free, licence-compatible DWG writer is used",
    "slddrw": "native SolidWorks drawings require the SolidWorks worker (not deployed)",
}


@router.get("/defaults", response_model=DrawingDefaults)
def drawing_defaults() -> DrawingDefaults:
    return DrawingDefaults(
        settings=DrawingSettings(),
        options={
            "drawing_kind": [k.value for k in DrawingKind],
            "drawing_standard": [s.value for s in DrawingStandard],
            "projection_method": [p.value for p in ProjectionMethod],
            "sheet_size": [s.value for s in SheetSize],
            "sheet_orientation": [o.value for o in SheetOrientation],
            "view_orientation": [v.value for v in ViewOrientation],
            "orthographic_view": [v.value for v in ViewOrientation
                                  if v not in (ViewOrientation.ISOMETRIC, ViewOrientation.DIMETRIC, ViewOrientation.TRIMETRIC)],
            "view_frame": [f.value for f in ViewFrame],
            "display_style": [d.value for d in DisplayStyle],
            "units": ["mm"],
        },
    )


def _get_model(session: Session, model_id: str, principal: Principal) -> CadModel:
    model = session.get(CadModel, model_id)
    if model is None or model.owner_id != principal.id:
        raise NotFound(f"model {model_id} not found")
    return model


def _start(session: Session, storage: Storage, runner: JobRunner, principal: Principal, model: CadModel,
           settings: DrawingSettings) -> DrawingAccepted:
    if model.status != ModelStatus.ANALYZED:
        raise Conflict(f"model is {model.status}; analyze it first", code="MODEL_NOT_ANALYZED")
    if model.format != "STEP":
        raise Conflict("drawing generation needs exact B-Rep geometry (STEP); STL is not supported yet",
                       code="STL_NOT_SUPPORTED")
    job = Job(owner_id=principal.id, kind=JobKind.DRAWING, model_id=model.id, state=JobState.QUEUED, message="Queued")
    session.add(job)
    session.flush()
    (storage.drawing_dir(job.id) / "settings.json").write_text(settings.model_dump_json(indent=2))
    session.commit()
    runner.submit(job.id)
    return DrawingAccepted(drawing_id=job.id, job_id=job.id, job=JobOut.from_row(job))


def get_drawing_job(session: Session, drawing_id: str, principal: Principal) -> Job:
    job = session.get(Job, drawing_id)
    if job is None or job.owner_id != principal.id or job.kind != JobKind.DRAWING:
        raise NotFound(f"drawing {drawing_id} not found")
    return job


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED, response_model=DrawingAccepted)
def generate_drawing(
    body: GenerateRequest,
    session: Session = Depends(get_session),
    storage: Storage = Depends(get_storage),
    runner: JobRunner = Depends(get_runner),
    principal: Principal = Depends(get_principal),
) -> DrawingAccepted:
    return _start(session, storage, runner, principal, _get_model(session, body.model_id, principal), body.settings)


@router.get("/{drawing_id}", response_model=DrawingOut)
def get_drawing(
    drawing_id: str,
    session: Session = Depends(get_session),
    storage: Storage = Depends(get_storage),
    principal: Principal = Depends(get_principal),
) -> DrawingOut:
    job = get_drawing_job(session, drawing_id, principal)
    d = storage.path("drawings", job.id)
    manifest = json.loads((d / "manifest.json").read_text()) if (d / "manifest.json").exists() else {}
    qa = QaReport.model_validate_json((d / "qa_report.json").read_text()) if (d / "qa_report.json").exists() else None
    downloads = [fmt for fmt, name in FORMATS.items() if (d / name).exists()] if manifest.get("qa_passed") else []
    return DrawingOut(
        id=job.id, model_id=job.model_id, job=JobOut.from_row(job),
        settings=DrawingSettings.model_validate_json((d / "settings.json").read_text()),
        passed=manifest.get("qa_passed"), scale=manifest.get("scale"), generator=manifest.get("generator"),
        solidworks=bool(manifest.get("solidworks", False)), downloads=downloads,
        unavailable_formats=UNAVAILABLE, qa=qa,
    )


@router.get("/{drawing_id}/plan")
def get_plan(drawing_id: str, session: Session = Depends(get_session), storage: Storage = Depends(get_storage),
             principal: Principal = Depends(get_principal)) -> dict:
    job = get_drawing_job(session, drawing_id, principal)
    p = storage.path("drawings", job.id, "plan.json")
    if not p.exists():
        raise Conflict("the plan is not available yet", code="JOB_NOT_COMPLETE")
    return json.loads(p.read_text())


@router.post("/{drawing_id}/validate", response_model=QaReport)
def validate_drawing(
    drawing_id: str,
    session: Session = Depends(get_session),
    storage: Storage = Depends(get_storage),
    principal: Principal = Depends(get_principal),
) -> QaReport:
    """Re-run the deterministic QA on the stored drawing (pure Python; nothing is modified)."""
    from drawing_qa import Rendered, validate
    from drawing_schema import DrawingPlan
    from drawing_schema.candidates import DimensionCandidate
    from drawing_schema.compiled import CompiledDrawing
    from geometry_schema import GeometryIR

    job = get_drawing_job(session, drawing_id, principal)
    d = storage.path("drawings", job.id)
    needed = ["plan.json", "candidates.json", "compiled.json", "rendered.json"]
    if job.state not in (JobState.COMPLETED, JobState.FAILED) or not all((d / n).exists() for n in needed):
        raise Conflict("the drawing has not been generated", code="JOB_NOT_COMPLETE")
    rendered = json.loads((d / "rendered.json").read_text())
    return validate(
        DrawingPlan.model_validate_json((d / "plan.json").read_text()),
        [DimensionCandidate.model_validate(c) for c in json.loads((d / "candidates.json").read_text())],
        GeometryIR.model_validate_json(storage.path("models", job.model_id, "geometry_ir.json").read_text()),
        CompiledDrawing.model_validate_json((d / "compiled.json").read_text()),
        Rendered(lines=rendered["lines"], snapped=rendered["snapped"]),
    )


@router.post("/{drawing_id}/regenerate", status_code=status.HTTP_202_ACCEPTED, response_model=DrawingAccepted)
def regenerate_drawing(
    drawing_id: str,
    body: RegenerateRequest | None = None,
    session: Session = Depends(get_session),
    storage: Storage = Depends(get_storage),
    runner: JobRunner = Depends(get_runner),
    principal: Principal = Depends(get_principal),
) -> DrawingAccepted:
    job = get_drawing_job(session, drawing_id, principal)
    settings = (body.settings if body and body.settings else
                DrawingSettings.model_validate_json(storage.path("drawings", job.id, "settings.json").read_text()))
    return _start(session, storage, runner, principal, _get_model(session, job.model_id, principal), settings)
