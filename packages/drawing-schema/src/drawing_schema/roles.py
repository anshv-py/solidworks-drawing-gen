"""Functional feature roles and rule-driven view triggers.

A role (bearing bore, dowel hole, mounting face ...) decides which tolerances, GD&T and finish the
primary rule set (drawing_planner/rules/drawing_rules.yaml) applies to a feature. Geometry cannot prove
a feature's function, so an INFERRED role is always an assumption: it is reported with its confidence
and reasons ("assumed role: X - confirm or override"). A USER role (an override, or a confirmation of
the guess) is keyed by the deterministic GeometryIR face / feature id, so it survives regeneration.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from drawing_schema.pmi import Target
from shared_types import StrictModel


class FeatureRole(StrEnum):
    MOUNTING_FACE = "MOUNTING_FACE"  # primary seating / fixturing face -> datum A
    SEALING_FACE = "SEALING_FACE"  # O-ring / gasket face -> datum A, tight flatness, fine finish
    BEARING_BORE = "BEARING_BORE"  # bore a bearing / bushing presses into
    CENTRAL_BORE = "CENTRAL_BORE"  # locating through-bore of a disc / flange
    BEARING_SEAT = "BEARING_SEAT"  # shaft journal carrying a bearing
    SHOULDER_FACE = "SHOULDER_FACE"  # shaft shoulder locating a bearing axially
    CLEARANCE_HOLES = "CLEARANCE_HOLES"  # bolt clearance holes (a pattern or a group)
    DOWEL_HOLE = "DOWEL_HOLE"  # locating pin hole
    TAPPED_HOLE = "TAPPED_HOLE"  # threaded hole
    KEYWAY = "KEYWAY"  # key seat milled into a shaft / boss
    SEAL_GROOVE = "SEAL_GROOVE"  # O-ring gland
    NONE = "NONE"  # no functional role: general tolerances only


FACE_ROLES = {FeatureRole.MOUNTING_FACE, FeatureRole.SEALING_FACE, FeatureRole.SHOULDER_FACE}


class RoleSource(StrEnum):
    INFERRED = "INFERRED"  # guessed from geometry by the rule set - to be confirmed
    USER = "USER"  # set or confirmed by the user


class RoleOverride(StrictModel):
    """A user's role for one face / feature (also used to confirm a guess)."""

    target: Target
    role: FeatureRole


class RoleAssignment(StrictModel):
    target: Target
    role: FeatureRole
    source: RoleSource
    confidence: float = Field(ge=0, le=1, description="1 for USER; the inference's confidence otherwise")
    description: str = Field(description="the feature in words, e.g. 'Ø40.00 THRU hole'")
    reasons: list[str] = Field(default_factory=list)
    rule: str = Field(default="", description="rule-set reference of the treatment, e.g. 'EX 4 F2'")


class ViewTriggerKind(StrEnum):
    ISOMETRIC = "ISOMETRIC"
    SECTION = "SECTION"
    DETAIL = "DETAIL"
    AUXILIARY = "AUXILIARY"
    BREAK = "BREAK"
    THICKNESS_NOTE = "THICKNESS_NOTE"


class ViewTrigger(StrictModel):
    """A view rule of the rule set that fired for this part."""

    kind: ViewTriggerKind
    rule: str
    message: str
    feature_ids: list[str] = Field(default_factory=list)
    satisfied: bool = Field(description="the drawing contains what the rule asks for")


__all__ = ["FACE_ROLES", "FeatureRole", "RoleAssignment", "RoleOverride", "RoleSource", "ViewTrigger",
           "ViewTriggerKind"]
