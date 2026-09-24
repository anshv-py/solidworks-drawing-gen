import json
import subprocess
import sys


def test_preview_mesh_has_one_group_per_face(analyzed):
    ir, preview = analyzed["flange"]
    assert {g["face_id"] for g in preview["groups"]} == {f.id for f in ir.faces}
    n_vertices = len(preview["positions"]) // 3
    assert max(preview["indices"]) < n_vertices
    assert len(preview["indices"]) % 3 == 0
    assert sum(g["count"] for g in preview["groups"]) == len(preview["indices"])
    assert {e["edge_id"] for e in preview["edges"]} <= {e.id for e in ir.edges}


def _run(args, tmp_path):
    return subprocess.run(
        [sys.executable, "-m", "geometry_service", "analyze", *args, "--output-dir", str(tmp_path / "out")],
        capture_output=True, text=True, timeout=120,
    )


def test_cli_protocol_success(models_dir, tmp_path):
    proc = _run(["--input", str(models_dir / "bracket.step"), "--format", "STEP"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    events = [json.loads(line) for line in proc.stdout.splitlines()]  # every stdout line is protocol JSON
    assert events[-1]["event"] == "result"
    assert any(e["event"] == "progress" for e in events)
    ir = json.loads((tmp_path / "out" / "geometry_ir.json").read_text())
    assert ir["schema_version"] == "0.1.0"
    assert (tmp_path / "out" / "preview_mesh.json").exists()


def test_cli_protocol_invalid_content(tmp_path):
    bad = tmp_path / "bad.step"
    bad.write_text("ISO-10303-21;\ngarbage\n")
    proc = _run(["--input", str(bad), "--format", "STEP"], tmp_path)
    assert proc.returncode == 2
    last = json.loads(proc.stdout.splitlines()[-1])
    assert last["event"] == "error" and last["code"].startswith("STEP_")


def test_cli_reports_missing_geometry_engine(models_dir, tmp_path):
    # e.g. a container without libGL: OCP fails to import -> structured error, not a crash
    code = (
        "import sys; sys.modules['OCP'] = None; from geometry_service.cli import main; "
        f"sys.exit(main(['analyze', '--input', r'{models_dir / 'bracket.step'}', '--format', 'STEP', "
        f"'--output-dir', r'{tmp_path / 'out'}']))"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    last = json.loads(proc.stdout.splitlines()[-1])
    assert last == {"event": "error", "code": "GEOMETRY_ENGINE_UNAVAILABLE", "message": last["message"]}
