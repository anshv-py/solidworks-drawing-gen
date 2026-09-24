"""Hosted single-service deployment (render.yaml): shared-password gate, UI served by the API,
hosted Postgres URLs."""

import base64

import pytest
from fastapi.testclient import TestClient

from cad_api.config import Settings
from cad_api.main import create_app


def make(tmp_path, **kw):
    return TestClient(create_app(Settings(storage_dir=tmp_path / "storage",
                                          database_url=f"sqlite:///{tmp_path}/test.db", **kw)))


def basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def test_password_gate_protects_everything_but_the_health_check(tmp_path):
    with make(tmp_path, access_password="s3cret") as c:
        assert c.get("/api/health").status_code == 200  # the host's health check stays open
        r = c.get("/api/drawings/defaults")
        assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
        assert c.get("/api/drawings/defaults", headers=basic("cadai", "wrong")).status_code == 401
        assert c.get("/api/drawings/defaults", headers=basic("other", "s3cret")).status_code == 401
        assert c.get("/api/drawings/defaults", headers=basic("cadai", "s3cret")).status_code == 200


def test_no_password_means_no_gate(tmp_path):
    with make(tmp_path) as c:
        assert c.get("/api/drawings/defaults").status_code == 200


def test_frontend_is_served_with_spa_fallback_and_no_traversal(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    with make(tmp_path, frontend_dir=dist) as c:
        assert c.get("/").text == "<html>app</html>"
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/models/123").text == "<html>app</html>"  # client-side route
        assert "nope" not in c.get("/../secret.txt").text
        assert "nope" not in c.get("/%2e%2e/secret.txt").text
        r = c.get("/api/no-such-route")
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
        assert c.get("/api/health").json()["status"] == "ok"  # API routes win over the SPA


@pytest.mark.parametrize("url", ["postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"])
def test_hosted_postgres_urls_use_psycopg(url):
    assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@h:5432/db"
    assert Settings(database_url="sqlite:////data/cadai.db").database_url == "sqlite:////data/cadai.db"
