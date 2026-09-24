"""Drawing planner - NOT IMPLEMENTED (milestone 2).

Contract: ``plan(geometry: GeometryIR, settings: UserDrawingSettings) -> DrawingPlan``.

Planned design:
1. Deterministic baseline plan from user settings (``drawing_schema.default_plan``).
2. Deterministic dimension-candidate engine over GeometryIR (candidate ids, values
   looked up from GeometryIR - never produced by the LLM).
3. Optional LLM refinement (OpenAI Responses API, model configurable, default
   ``gpt-5.6-sol``) constrained by a JSON-schema structured output of DrawingPlan.
   The LLM sees GeometryIR summaries and candidate ids only.
4. Deterministic validation of the returned plan (schema + referential checks).
"""

STATUS = "NOT_IMPLEMENTED"
