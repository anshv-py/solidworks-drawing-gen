import time

import pytest
from fastapi.testclient import TestClient

from cad_api.config import Settings
from cad_api.errors import ApiError
from cad_api.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        storage_dir=tmp_path / "storage",
        database_url=f"sqlite:///{tmp_path}/test.db",
        max_upload_mb=1,
        analysis_timeout_s=120,
    )
    with TestClient(create_app(settings)) as c:
        yield c


def upload(client, path, name=None):
    with open(path, "rb") as fh:
        return client.post("/api/models/upload", files={"file": (name or path.name, fh)})


def wait(client, job_id, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("COMPLETED", "FAILED"):
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_upload_analyze_geometry_preview(client, models_dir):
    r = upload(client, models_dir / "plate_with_holes.step")
    assert r.status_code == 201
    model = r.json()
    assert model["format"] == "STEP" and model["status"] == "UPLOADED"

    assert client.get(f"/api/models/{model['id']}/geometry").status_code == 409  # not analyzed yet

    r = client.post(f"/api/models/{model['id']}/analyze")
    assert r.status_code == 202
    job = wait(client, r.json()["job_id"])
    assert job["state"] == "COMPLETED", job
    assert job["progress"] == 100.0

    model = client.get(f"/api/models/{model['id']}").json()
    assert model["status"] == "ANALYZED" and model["feature_count"] == 6

    ir = client.get(f"/api/models/{model['id']}/geometry").json()
    assert ir["bounding_box"]["size"] == pytest.approx([120, 80, 10])
    assert ir["representation"] == "EXACT_BREP"
    mesh = client.get(f"/api/models/{model['id']}/preview-mesh").json()
    assert mesh["format"] == "cad-drawing-ai/preview-mesh@1" and mesh["groups"]


def test_stl_upload_and_analysis(client, models_dir):
    model = upload(client, models_dir / "bracket.stl").json()
    assert model["format"] == "STL"
    job = wait(client, client.post(f"/api/models/{model['id']}/analyze").json()["job_id"])
    assert job["state"] == "COMPLETED"
    ir = client.get(f"/api/models/{model['id']}/geometry").json()
    assert ir["representation"] == "TESSELLATED"


def test_invalid_step_content_fails_job_cleanly(client, tmp_path):
    bad = tmp_path / "broken.step"
    bad.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
    model = upload(client, bad).json()
    job = wait(client, client.post(f"/api/models/{model['id']}/analyze").json()["job_id"])
    assert job["state"] == "FAILED"
    assert job["error"]["code"].startswith("STEP_")
    assert client.get(f"/api/models/{model['id']}").json()["status"] == "FAILED"


@pytest.mark.parametrize(
    "name,content,code,status",
    [
        ("model.obj", b"v 0 0 0", "UNSUPPORTED_FILE_TYPE", 415),
        ("model.step", b"", "INVALID_CAD_CONTENT", 415),
        ("model.step", b"MZ\x90\x00 not a step", "INVALID_CAD_CONTENT", 415),
        ("model.stl", b"ISO-10303-21;\nHEADER;", "EXTENSION_MISMATCH", 415),
    ],
)
def test_upload_validation(client, name, content, code, status):
    r = client.post("/api/models/upload", files={"file": (name, content)})
    assert r.status_code == status
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == code


def test_upload_size_limit(client):
    big = b"ISO-10303-21;\n" + b"x" * (1024 * 1024 + 10)
    r = client.post("/api/models/upload", files={"file": ("big.step", big)})
    assert r.status_code == 413 and r.json()["code"] == "FILE_TOO_LARGE"


def test_filename_is_sanitized_and_never_used_as_path(client, models_dir):
    r = upload(client, models_dir / "shaft.step", name="../../etc/passwd.step")
    assert r.status_code == 201
    assert r.json()["original_filename"] == "passwd.step"


def test_storage_refuses_path_traversal(client):
    storage = client.app.state.storage
    with pytest.raises(ApiError):
        storage.path("..", "..", "etc", "passwd")


def test_not_found(client):
    assert client.get("/api/models/nope").status_code == 404
    assert client.get("/api/jobs/nope").status_code == 404


def test_analysis_job_has_no_drawing_artifacts(client, models_dir):
    model = upload(client, models_dir / "shaft.step").json()
    job_id = client.post(f"/api/models/{model['id']}/analyze").json()["job_id"]
    wait(client, job_id)
    r = client.get(f"/api/jobs/{job_id}/download/pdf")
    assert r.status_code == 409 and r.json()["code"] == "NOT_A_DRAWING_JOB"
    assert client.get(f"/api/jobs/{job_id}/download/exe").status_code == 404


def test_drawing_defaults(client):
    body = client.get("/api/drawings/defaults").json()
    s = body["settings"]
    assert s["primary_view"] == "ISOMETRIC" and s["projection_method"] == "FIRST_ANGLE"
    assert s["drawing_standard"] == "ISO" and s["sheet"] == {
        "size": "A3", "orientation": "LANDSCAPE", "scale": "AUTO", "pictorial_scale": "AUTO",
        "scale_system": "INTERMEDIATE"}
    assert "Y_UP" in body["options"]["view_frame"]
    o = body["options"]
    assert o["scale"][0] == "AUTO" and "1:1.5" in o["scale"] and "1:1.5" not in o["iso_scale"]
    assert o["scale_system"] == ["ISO_5455", "INTERMEDIATE"]
