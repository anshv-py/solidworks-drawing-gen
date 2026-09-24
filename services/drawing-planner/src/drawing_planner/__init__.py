"""Drawing planner - NOT IMPLEMENTED (milestone 2).

Contract: ``plan(geometry: GeometryIR, settings: UserDrawingSettings) -> DrawingPlan``.

Planned design:
1. Deterministic baseline plan from user settings (``drawing_schema.default_plan``).
2. Deterministic dimension-candidate engine over GeometryIR (candidate ids, values
   looked up from GeometryIR - never produced by the LLM).
3. Optional LLM refinement with DeepSeek-V4-Pro (``deepseek-ai/DeepSeek-V4-Pro``,
   Hugging Face ``transformers``; configurable) producing a DrawingPlan JSON that must
   validate against the DrawingPlan schema (constrained decoding where the backend
   supports it, otherwise validate-and-retry). Runs in a GPU planner worker, not the API.
   The LLM sees GeometryIR summaries and candidate ids only.
4. Deterministic validation of the returned plan (schema + referential checks).
"""

STATUS = "NOT_IMPLEMENTED"
