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
    # primary rule set: a simple turned flange gets no isometric (RULES 1.2) and the fewest views (RULES 1.1)
    assert plan["rule_set"].startswith("CADAI-MFG-RULES")
    assert plan["primary_view"]["orientation"] == "FRONT" and plan["projected_views"] == ["TOP"]
    # compliance gate: no part number / material / revision -> stamped, downloadable, not releasable
    c = d["compliance"]
    assert c["releasable"] is False and c["stamp"].startswith("NOT FOR MANUFACTURE")
    assert {i["number"] for i in c["items"] if i["status"] == "FAIL"} == {1, 11}
    assert {a["role"] for a in c["assumed_roles"]} >= {"CENTRAL_BORE", "MOUNTING_FACE"}
    r = client.post(f"/api/drawings/{drawing_id}/release")
    assert r.status_code == 409 and r.json()["code"] == "RELEASE_BLOCKED" and "revision" in r.json()["detail"]
    qa = client.post(f"/api/drawings/{drawing_id}/validate").json()
    assert qa["passed"] is True and "QA-VIEW-002" in qa["checks_run"]

    r = client.post(f"/api/drawings/{drawing_id}/regenerate",
                    json={"settings": {"projection_method": "THIRD_ANGLE", "sheet": {"size": "A2"}}})
    assert r.status_code == 202 and r.json()["drawing_id"] != drawing_id
    job2 = wait(client, r.json()["drawing_id"], timeout=180)
    assert job2["state"] == "COMPLETED"
    d2 = client.get(f"/api/drawings/{r.json()['drawing_id']}").json()
    assert d2["settings"]["projection_method"] == "THIRD_ANGLE" and d2["settings"]["sheet"]["size"] == "A2"

    # the hard blockers filled in -> releasable, no stamp; release is recorded once
    complete = {"title_block": {"part_number": "FL-100", "revision": "A"},
                "engineering_information": {"material": {"status": "SPECIFIED", "value": "EN AW-6082 T6",
                                                         "source": "USER"}}}
    r = client.post("/api/drawings/generate", json={"model_id": model["id"], "settings": complete})
    rid = r.json()["drawing_id"]
    assert wait(client, rid, timeout=180)["state"] == "COMPLETED"
    d3 = client.get(f"/api/drawings/{rid}").json()
    assert d3["compliance"]["releasable"] is True and d3["compliance"]["stamp"] is None and d3["released"] is False
    rel = client.post(f"/api/drawings/{rid}/release")
    assert rel.status_code == 200 and rel.json()["released"] is True and rel.json()["released_at"]


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


def test_annotation_targets_and_invalid_annotations(client, models_dir):  # noqa: F811
    model = analyzed_model(client, models_dir / "flange.step")
    t = client.post("/api/drawings/annotation-targets", json={"model_id": model["id"], "settings": {}}).json()
    ids = {d["id"] for d in t["dimensions"]}
    assert "DIM-OVERALL-Z" in ids and any(d["text"].startswith("8X") for d in t["dimensions"])
    assert len(t["planar_faces"]) == 3 and any(f["type"] == "PATTERN" for f in t["features"])
    # references that do not exist on this part are rejected before a job is queued
    bad = {"manufacturing": {"tolerances": [{"candidate_id": "DIM-NOPE", "kind": "SYMMETRIC", "upper": 0.1}]}}
    r = client.post("/api/drawings/generate", json={"model_id": model["id"], "settings": bad})
    assert r.status_code == 422 and r.json()["code"] == "PMI_INVALID"
    face = t["planar_faces"][0]["id"]
    ok = {"manufacturing": {"datums": [{"letter": "A", "target": {"face_id": face}}],
                            "tolerances": [{"candidate_id": "DIM-OVERALL-Z", "kind": "SYMMETRIC", "upper": 0.1}]}}
    assert client.post("/api/drawings/generate", json={"model_id": model["id"], "settings": ok}).status_code == 202


@pytest.mark.slow
def test_new_cad_version_regenerates_the_drawing_with_a_revision(client, models_dir):  # noqa: F811
    """EX 2: a new version of a part is analysed -> its drawing is regenerated automatically, the user's
    annotations re-pointed to the changed features, a revision logged and a change report stored."""
    v1 = analyzed_model(client, models_dir / "plate_with_holes.step")
    geo = client.get(f"/api/models/{v1['id']}/geometry").json()
    bore = max((f for f in geo["features"] if f["type"] == "HOLE"), key=lambda f: f["diameter"])
    settings = {"title_block": {"revision": "A"},
                "feature_roles": [{"target": {"feature_id": bore["id"]}, "role": "BEARING_BORE"}]}
    first = client.post("/api/drawings/generate", json={"model_id": v1["id"], "settings": settings}).json()
    assert wait(client, first["drawing_id"], timeout=180)["state"] == "COMPLETED"

    with open(models_dir / "plate_with_holes_rev_b.step", "rb") as fh:
        v2 = client.post("/api/models/upload", files={"file": ("plate_with_holes.step", fh)},
                         data={"previous_model_id": v1["id"]}).json()
    assert v2["previous_model_id"] == v1["id"]
    assert wait(client, client.post(f"/api/models/{v2['id']}/analyze").json()["job_id"])["state"] == "COMPLETED"
    drawings = client.get(f"/api/models/{v2['id']}/drawings").json()
    assert len(drawings) == 1  # started by the analysis, nobody asked
    assert wait(client, drawings[0]["id"], timeout=180)["state"] == "COMPLETED"
    d = client.get(f"/api/drawings/{drawings[0]['id']}").json()
    rep = d["change_report"]
    assert rep["previous_drawing_id"] == first["drawing_id"] and rep["revision"] == "B"
    assert rep["diff"]["summary"] == "ADDED HOLE Ø5; RESIZED HOLE Ø22" and rep["dropped"] == []
    new_bore = rep["diff"]["resized"][0][1]
    assert d["settings"]["feature_roles"] == [{"target": {"feature_id": new_bore, "face_id": None},
                                               "role": "BEARING_BORE"}]
    revs = d["settings"]["manufacturing"]["revisions"]
    assert [r["revision"] for r in revs] == ["A", "B"] and revs[1]["description"] == rep["diff"]["summary"]
    assert d["settings"]["title_block"]["revision"] == "B"
    eleven = next(i for i in d["compliance"]["items"] if i["number"] == 11)
    assert eleven["status"] == "PASS"


def test_previous_version_must_be_your_own_model(client, models_dir):  # noqa: F811
    with open(models_dir / "plate_with_holes.step", "rb") as fh:
        r = client.post("/api/models/upload", files={"file": ("p.step", fh)}, data={"previous_model_id": "nope"})
    assert r.status_code == 404
