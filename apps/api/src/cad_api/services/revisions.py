"""EX 2 automation: when a new CAD version (a model uploaded with ``previous_model_id``) has been analysed,
the previous version's latest drawing is regenerated for it - settings carried over (ids re-pointed,
orphans dropped), a revision entry appended - and a change report is stored with the new drawing."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from cad_api.db import CadModel, Job, JobKind, JobState
from cad_api.services.storage import Storage

log = logging.getLogger(__name__)


def start_revision_drawing(session: Session, storage: Storage, model: CadModel) -> str | None:
    """-> the id of the drawing job started for ``model`` (a new version), or None if there is nothing to
    regenerate. The caller commits (together with the analysis result) and submits the job."""
    from drawing_planner.revisions import carry_settings, diff_features
    from drawing_schema.settings import DrawingSettings
    from geometry_schema import GeometryIR

    if not model.previous_model_id:
        return None
    prev = session.get(CadModel, model.previous_model_id)
    if prev is None or prev.owner_id != model.owner_id:
        return None
    drawing = session.scalars(
        select(Job).where(Job.model_id == prev.id, Job.kind == JobKind.DRAWING, Job.state == JobState.COMPLETED)
        .order_by(Job.created_at.desc())).first()
    if drawing is None:
        return None
    old_ir = GeometryIR.model_validate_json(storage.path("models", prev.id, "geometry_ir.json").read_text())
    new_ir = GeometryIR.model_validate_json(storage.path("models", model.id, "geometry_ir.json").read_text())
    previous = DrawingSettings.model_validate_json(storage.path("drawings", drawing.id, "settings.json").read_text())
    diff = diff_features(old_ir, new_ir)
    carried = carry_settings(previous, old_ir, new_ir, diff)
    job = Job(owner_id=model.owner_id, kind=JobKind.DRAWING, model_id=model.id, state=JobState.QUEUED,
              message=f"Queued: revision {carried.revision} for the new CAD version")
    session.add(job)
    session.flush()
    out = storage.drawing_dir(job.id)
    (out / "settings.json").write_text(carried.settings.model_dump_json(indent=2))
    (out / "change_report.json").write_text(json.dumps({
        "previous_model_id": prev.id, "previous_drawing_id": drawing.id, "revision": carried.revision,
        "diff": diff.as_dict(), "carried": carried.carried, "dropped": carried.dropped,
        "regeneration": "complete and deterministic from the carried settings (no manual sheet edits exist)",
    }, indent=2))
    log.info("revision drawing queued", extra={"job_id": job.id, "model_id": model.id})
    return job.id


__all__ = ["start_revision_drawing"]
