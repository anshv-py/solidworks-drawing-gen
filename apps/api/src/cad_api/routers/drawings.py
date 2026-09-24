"""Drawing endpoints. Contracts exist; generation arrives in later milestones.

These return 501 rather than fake results: no drawing is ever reported as
generated unless it was actually produced.
"""

from __future__ import annotations

from fastapi import APIRouter

from drawing_schema import (
    DisplayStyle,
    DrawingKind,
    DrawingStandard,
    ProjectionMethod,
    SheetOrientation,
    SheetSize,
    ViewOrientation,
    ISO_5455_SCALES,
    default_plan,
)
from cad_api.errors import NotImplementedYet
from cad_api.schemas import DrawingDefaults

router = APIRouter(prefix="/api/drawings", tags=["drawings"])


@router.get("/defaults", response_model=DrawingDefaults)
def drawing_defaults() -> DrawingDefaults:
    return DrawingDefaults(
        plan=default_plan(source_sha256="0" * 64),
        options={
            "drawing_kind": [k.value for k in DrawingKind],
            "drawing_standard": [s.value for s in DrawingStandard],
            "projection_method": [p.value for p in ProjectionMethod],
            "sheet_size": [s.value for s in SheetSize],
            "sheet_orientation": [o.value for o in SheetOrientation],
            "view_orientation": [v.value for v in ViewOrientation],
            "display_style": [d.value for d in DisplayStyle],
            "scale": ["AUTO", *ISO_5455_SCALES],
            "units": ["mm"],
        },
    )


@router.post("/generate", status_code=501)
def generate_drawing() -> None:
    raise NotImplementedYet("drawing generation is not implemented yet (next milestones: planner, compiler, worker)")


@router.post("/{drawing_id}/validate", status_code=501)
def validate_drawing(drawing_id: str) -> None:
    raise NotImplementedYet("drawing QA is not implemented yet")


@router.post("/{drawing_id}/regenerate", status_code=501)
def regenerate_drawing(drawing_id: str) -> None:
    raise NotImplementedYet("drawing regeneration is not implemented yet")
