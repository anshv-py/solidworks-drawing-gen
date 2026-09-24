"""The CAD job process environment must work without the parent's home variables.

On Windows ``Path.home()`` needs USERPROFILE; a missing one made ezdxf fail at import with
"RuntimeError: Could not determine home directory." These tests make the home lookup fail on
purpose (as on that Windows machine) and check the job environment still imports everything.
"""

import subprocess
import sys

from cad_api.services.jobs import child_env

# Emulate Windows (Python >= 3.8): "~" expands to %USERPROFILE% only; HOME is ignored, and without
# USERPROFILE (or HOMEDRIVE/HOMEPATH) Path.home() raises exactly the error seen on the user's machine.
WINDOWS_HOME = (
    "import os, pathlib, posixpath\n"
    "def home():\n"
    "    p = os.environ.get('USERPROFILE')\n"
    "    if not p: raise RuntimeError('Could not determine home directory.')\n"
    "    return p\n"
    "def expand(path):\n"
    "    s = os.fspath(path)\n"
    "    return home() + s[1:] if s.startswith('~') else s\n"
    "os.path.expanduser = posixpath.expanduser = expand\n"
    "pathlib.Path.expanduser = lambda self: type(self)(expand(self))\n"
    "pathlib.Path.home = classmethod(lambda cls: cls(home()))\n"
)


def _run(code: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", WINDOWS_HOME + code], env=env, capture_output=True, text=True,
                          timeout=120)


def test_home_lookup_failure_is_reproduced_without_the_fix(tmp_path):
    env = child_env(tmp_path, platform="linux")  # POSIX env only: no USERPROFILE, as before the fix
    out = _run("import ezdxf", env)
    assert out.returncode != 0 and "Could not determine home directory" in out.stderr


def test_job_env_imports_drawing_stack_without_home(tmp_path):
    out = _run("import ezdxf, matplotlib; import drawing_executor.render; print('ok')",
               child_env(tmp_path, platform="win32"))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


def test_windows_env_has_profile_dirs_and_no_secrets(tmp_path):
    parent = {"PATH": r"C:\\Windows", "SYSTEMROOT": r"C:\\Windows", "CADAI_OPENAI_API_KEY": "secret",
              "AWS_SECRET_ACCESS_KEY": "secret"}
    env = child_env(tmp_path, platform="win32", parent=parent)
    for key in ("USERPROFILE", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "MPLCONFIGDIR"):
        assert env[key].startswith(str(tmp_path)), key
    assert env["SYSTEMROOT"] == r"C:\\Windows"
    assert not any("SECRET" in k or "API_KEY" in k for k in env)
