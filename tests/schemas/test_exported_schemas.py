import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_committed_json_schemas_are_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/export_schemas.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
