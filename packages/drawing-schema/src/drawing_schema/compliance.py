"""Compliance report: the Universal Mandatory Minimum of the primary rule set (EX 1), per drawing.

Hard-blocker failures stamp the sheet "NOT FOR MANUFACTURE" and make the explicit release step refuse;
they never stop generation or downloads. Warnings are reported.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from drawing_schema.roles import RoleAssignment, ViewTrigger
from shared_types import StrictModel


class ComplianceStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ComplianceItem(StrictModel):
    number: int = Field(ge=1, le=12, description="item of the Universal Mandatory Minimum (EX 1)")
    requirement: str
    hard_blocker: bool
    status: ComplianceStatus
    details: list[str] = Field(default_factory=list)


class ComplianceReport(StrictModel):
    rule_set: str = Field(description="id and version of the rule set that produced the drawing")
    items: list[ComplianceItem]
    assumed_roles: list[RoleAssignment] = Field(
        default_factory=list, description="roles guessed from geometry - confirm or override each")
    view_triggers: list[ViewTrigger] = Field(default_factory=list)
    releasable: bool = Field(description="no hard blocker failed")
    stamp: str | None = Field(default=None, description="text stamped on the sheet when not releasable")

    @property
    def blocking(self) -> list[ComplianceItem]:
        return [i for i in self.items if i.hard_blocker and i.status == ComplianceStatus.FAIL]


__all__ = ["ComplianceItem", "ComplianceReport", "ComplianceStatus"]
