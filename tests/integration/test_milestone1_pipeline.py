"""Milestone 1 end-to-end: STEP upload -> OCCT (subprocess) -> GeometryIR -> features -> API -> preview mesh."""

import time

import pytest
from fastapi.testclient import TestClient

from cad_api.config import Settings
from cad_api.main import create_app

MODELS = ["plate_with_holes", "mounting_plate", "pocketed_block", "bracket", "shaft", "flange",
          "cylindrical_part", "enclosure", "chamfered_block"]


@pytest.mark.slow
def test_all_fixtures_through_http(tmp_path, models_dir, manifest):
    settings = Settings(storage_dir=tmp_path / "s", database_url=f"sqlite:///{tmp_path}/db.sqlite", job_workers=4)
    with TestClient(create_app(settings)) as client:
        jobs = {}
        for name in MODELS:
            with open(models_dir / f"{name}.step", "rb") as fh:
                model = client.post("/api/models/upload", files={"file": (f"{name}.step", fh)}).json()
            jobs[name] = (model["id"], client.post(f"/api/models/{model['id']}/analyze").json()["job_id"])
        deadline = time.monotonic() + 300
        for name, (model_id, job_id) in jobs.items():
            while (job := client.get(f"/api/jobs/{job_id}").json())["state"] not in ("COMPLETED", "FAILED"):
                assert time.monotonic() < deadline
                time.sleep(0.1)
            assert job["state"] == "COMPLETED", (name, job)
            ir = client.get(f"/api/models/{model_id}/geometry").json()
            assert ir["bounding_box"]["size"] == pytest.approx(manifest["models"][name]["expected"]["bbox_size"])
            mesh = client.get(f"/api/models/{model_id}/preview-mesh").json()
            assert {g["face_id"] for g in mesh["groups"]} == {f["id"] for f in ir["faces"]}
