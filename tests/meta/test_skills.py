"""STEP 2 verification: every Skill has valid frontmatter, focused scope and supporting files."""

import re
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[2] / ".claude" / "skills"
EXPECTED = {
    "cad-engineering-automation",
    "solidworks-api-automation",
    "cad-drawing-qa",
    "occt-geometry-step",
    "production-software-engineering",
}


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n"), path
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


def test_exactly_the_five_skills_exist():
    assert {p.name for p in SKILLS.iterdir() if p.is_dir()} == EXPECTED


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_skill_structure(name):
    d = SKILLS / name
    meta = frontmatter(d / "SKILL.md")
    assert meta["name"] == name
    desc = meta["description"]
    assert 100 < len(desc) <= 1024
    assert "Activate when" in desc and "Do NOT use" in desc  # states when (and when not) to activate
    for sub in ("references", "examples"):
        files = [p for p in (d / sub).iterdir() if p.is_file()]
        assert files, f"{name}/{sub} is empty"
    body = (d / "SKILL.md").read_text()
    for ref in re.findall(r"`((?:references|examples)/[^`\s]+\.\w+)`", body):
        assert (d / ref).exists(), f"{name}: SKILL.md references missing {ref}"


def test_skills_point_to_each_other_instead_of_overlapping():
    for name in EXPECTED:
        desc = frontmatter(SKILLS / name / "SKILL.md")["description"]
        others = EXPECTED - {name}
        assert sum(o in desc for o in others) >= 2, name
