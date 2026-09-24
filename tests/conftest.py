"""Shared fixtures. CAD models are generated fresh per test session from construction
parameters (scripts/generate_fixtures.py); expected values come from its manifest."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_fixtures", ROOT / "scripts" / "generate_fixtures.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_fixtures"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def fixture_models(tmp_path_factory) -> tuple[Path, dict]:
    out = tmp_path_factory.mktemp("models")
    manifest = _load_generator().generate(out)
    return out, manifest


@pytest.fixture(scope="session")
def models_dir(fixture_models) -> Path:
    return fixture_models[0]


@pytest.fixture(scope="session")
def manifest(fixture_models) -> dict:
    return fixture_models[1]


@pytest.fixture(scope="session")
def analyzed(models_dir, manifest):
    """GeometryIR for every STEP fixture (computed once per session)."""
    from geometry_service.analyze import analyze_file
    from shared_types import SourceFormat

    out = {}
    for name, entry in manifest["models"].items():
        ir, preview = analyze_file(models_dir / entry["step"], SourceFormat.STEP)
        out[name] = (ir, preview)
    return out
