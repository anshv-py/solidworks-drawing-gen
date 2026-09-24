"""Drawing planner: GeometryIR + DrawingSettings -> DrawingPlan.

The baseline planner is fully deterministic (no LLM). Every dimension value comes from
GeometryIR via the candidate engine; the plan only selects candidate ids and views.
An LLM refinement step is optional future work and is not required for a complete plan.
"""

from drawing_planner.baseline import PlanResult, plan_baseline, remove_redundant
from drawing_planner.candidates import generate_candidates

__all__ = ["PlanResult", "plan_baseline", "remove_redundant", "generate_candidates"]
