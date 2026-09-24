"""QA report contract (deterministic checks; visual QA would add advisory issues)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from drawing_schema.compiled import Rect
from shared_types import StrictModel


class QaSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class QaIssue(StrictModel):
    check_id: str
    severity: QaSeverity
    message: str
    entity_refs: list[str] = Field(default_factory=list)
    bbox: Rect | None = None
    repair: str | None = Field(default=None, description="repair action the compiler understands")


class QaReport(StrictModel):
    iteration: int
    passed: bool = Field(description="no CRITICAL issues")
    critical: int
    major: int
    minor: int
    checks_run: list[str]
    issues: list[QaIssue]
