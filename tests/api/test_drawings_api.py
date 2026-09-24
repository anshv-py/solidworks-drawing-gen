import subprocess
import sys

import pytest

from tests.api.test_api import client, upload, wait  # noqa: F401 - reuse fixtures/helpers


def analyzed_model(client, path):  # noqa: F811
    model = upload(client, path).json()
    job = wait(client, client.post(f"/api/models/{model['id']}/analyze").json()["job_id"])
    assert job["state"] == "COMPLETED"
    return model


@pytest.mark.slow
def test_generate_preview_download(client, models_dir):  # noqa: F811
    model = analyzed_model(client, models_dir / "flange.step")
    r = client.post("/api/drawings/generate", json={"model_id": model["id"], "settings": {}})
    assert r.status_code == 202
    drawing_id = r.json()["drawing_id"]
    job = wait(client, drawing_id, timeout=180)
    assert job["state"] == "COMPLETED", job
    assert job["kind"] == "DRAWING" and job["progress"] == 100.0

    d = client.get(f"/api/drawings/{drawing_id}").json()
    assert d["passed"] is True and d["solidworks"] is False
    assert "OCCT HLR" in d["generator"]
    assert set(d["downloads"]) == {"pdf", "dxf", "svg"}
    assert d["qa"]["critical"] == 0
    assert d["settings"]["projection_method"] == "FIRST_ANGLE"

    png = client.get(f"/api/jobs/{drawing_id}/preview")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    pdf = client.get(f"/api/jobs/{drawing_id}/download/pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    assert "attachment" in pdf.headers["content-disposition"]
    dxf = client.get(f"/api/jobs/{drawing_id}/download/dxf")
    assert dxf.status_code == 200 and b"DIMENSION" in dxf.content
    for fmt in ("dwg", "slddrw"):  # never faked
        r = client.get(f"/api/jobs/{drawing_id}/download/{fmt}")
        assert r.status_code == 501 and r.json()["code"] == "FORMAT_REQUIRES_SOLIDWORKS"

    plan = client.get(f"/api/drawings/{drawing_id}/plan").json()
    assert plan["primary_view"]["orientation"] == "ISOMETRIC"
    qa = client.post(f"/api/drawings/{drawing_id}/validate").json()
    assert qa["passed"] is True and "QA-VIEW-002" in qa["checks_run"]

    r = client.post(f"/api/drawings/{drawing_id}/regenerate",
                    json={"settings": {"projection_method": "THIRD_ANGLE", "sheet": {"size": "A2"}}})
    assert r.status_code == 202 and r.json()["drawing_id"] != drawing_id
    job2 = wait(client, r.json()["drawing_id"], timeout=180)
    assert job2["state"] == "COMPLETED"
    d2 = client.get(f"/api/drawings/{r.json()['drawing_id']}").json()
    assert d2["settings"]["projection_method"] == "THIRD_ANGLE" and d2["settings"]["sheet"]["size"] == "A2"


def test_generate_requires_analysis_and_step(client, models_dir):  # noqa: F811
    model = upload(client, models_dir / "bracket.step").json()
    r = client.post("/api/drawings/generate", json={"model_id": model["id"]})
    assert r.status_code == 409 and r.json()["code"] == "MODEL_NOT_ANALYZED"
    stl = analyzed_model(client, models_dir / "bracket.stl")
    r = client.post("/api/drawings/generate", json={"model_id": stl["id"]})
    assert r.status_code == 409 and r.json()["code"] == "STL_NOT_SUPPORTED"


def test_invalid_settings_rejected(client, models_dir):  # noqa: F811
    model = analyzed_model(client, models_dir / "shaft.step")
    r = client.post("/api/drawings/generate",
                    json={"model_id": model["id"], "settings": {"projected_views": ["ISOMETRIC"]}})
    assert r.status_code == 422
    r = client.post("/api/drawings/generate",
                    json={"model_id": model["id"], "settings": {"drawing_kind": "MANUFACTURING"}})
    assert r.status_code == 422  # manufacturing drawings need supplied material/tolerance


def test_unknown_drawing(client):  # noqa: F811
    assert client.get("/api/drawings/nope").status_code == 404


def test_api_process_never_loads_occt():
    code = "import sys, cad_api.main, cad_api.routers.drawings; print('OCP' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "False", out.stderr


def test_crash_reports_the_cause(client, models_dir, monkeypatch):  # noqa: F811
    """A drawing process that dies without a structured error must still say why."""
    model = analyzed_model(client, models_dir / "shaft.step")
    runner = client.app.state.runner
    orig = runner._run_process

    def broken(job_id, argv, cwd, on_progress):
        if "drawing_executor" in argv:
            argv = ["-c", "import drawing_executor_missing_module"]
        return orig(job_id, argv, cwd, on_progress)

    monkeypatch.setattr(runner, "_run_process", broken)
    drawing_id = client.post("/api/drawings/generate", json={"model_id": model["id"]}).json()["drawing_id"]
    job = wait(client, drawing_id)
    assert job["state"] == "FAILED"
    assert job["error"]["code"] == "JOB_CRASHED"
    assert "ModuleNotFoundError" in job["error"]["message"]
    d = client.get(f"/api/drawings/{drawing_id}").json()
    assert d["qa"] is None and d["downloads"] == []
