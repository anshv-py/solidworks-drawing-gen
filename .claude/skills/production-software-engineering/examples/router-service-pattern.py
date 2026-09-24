"""Illustrative router → service → repository layering (mirrors apps/api)."""
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelService:
    def __init__(self, repo, storage, runner):
        self.repo, self.storage, self.runner = repo, storage, runner

    def start_analysis(self, model_id: str) -> str:
        model = self.repo.get(model_id)          # raises NotFound -> 404 in handler
        job = self.repo.create_job(model.id, kind="ANALYZE")
        self.runner.submit(job.id)               # subprocess / queue, never inline OCCT
        return job.id


def get_model_service() -> ModelService: ...  # wired in dependencies.py


@router.post("/{model_id}/analyze", status_code=202)
def analyze(model_id: str, svc: ModelService = Depends(get_model_service)) -> dict:
    return {"job_id": svc.start_analysis(model_id)}
