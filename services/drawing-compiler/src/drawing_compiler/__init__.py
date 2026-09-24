"""Drawing compiler - NOT IMPLEMENTED (milestone 3).

Contract: ``compile(plan: DrawingPlan, geometry: GeometryIR) -> DrawingOps``.

Deterministically lowers a validated DrawingPlan into an ordered list of
worker operations (see .claude/skills/solidworks-api-automation/examples/
drawing-ops.json). Performs view layout on the sheet (projection method,
ISO 5455 scale selection) and resolves every dimension candidate id to
GeometryIR entities. Contains no LLM calls.
"""

STATUS = "NOT_IMPLEMENTED"
