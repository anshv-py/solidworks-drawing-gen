# Drawing engine (design - not implemented)

```
GeometryIR ─► dimension-candidate engine (deterministic)
           └► planner: rules baseline + optional LLM refinement (structured output: DrawingPlan)
DrawingPlan ─► validator (schema + referential + standards rules)
            ─► compiler: view layout (projection method, ISO 5455 scale), candidate → entity refs
            ─► DrawingOps (versioned JSON) ─► SolidWorks worker
```

## Dimension candidates (planned)
Deterministic from GeometryIR: overall extents; hole Ø/depth/position (to edges, to each other,
PCD); pattern pitch; pocket L/W/depth/corner R; slot width/length; fillet R; chamfer legs/angle;
boss Ø/height; thickness; feature-to-reference distances. Each candidate: id, kind, value (from
GeometryIR), entity refs, preferred view, priority. The planner selects ids; values are never
supplied by the LLM (the DrawingPlan schema has no value field).

## LLM usage (planned)
Model: **DeepSeek-V4-Pro** (`deepseek-ai/DeepSeek-V4-Pro` on the Hugging Face Hub, MIT licence),
run with Hugging Face `transformers`; configurable via `CADAI_LLM_MODEL` / `CADAI_LLM_REVISION`.
Input: GeometryIR summary + dimension-candidate ids + user settings. Output: DrawingPlan JSON,
validated against the DrawingPlan schema. Constrained decoding is used where the backend supports
it; otherwise the output is validated, rejected on failure and retried. Plans never contain values.

What was checked (web search, 2026-09-24; huggingface.co itself was blocked from the sandbox):
- 1.6T-parameter MoE, 49B active, 1M-token context, MIT licence.
- The FP4/FP8 instruct checkpoint is about 865 GB. Reported hardware: Blackwell (B200/B300) for native
  FP4 on one node, or 16+ H100 at FP8.
- vLLM and SGLang have official V4 recipes with OpenAI-compatible endpoints.

Consequences for the architecture:
- The model **never** loads in the API process. It runs in a dedicated GPU planner worker
  (`CADAI_LLM_BACKEND=transformers`) or behind a served endpoint
  (`CADAI_LLM_BACKEND=openai_compatible`, `CADAI_LLM_ENDPOINT_URL`), for example vLLM, SGLang or
  `transformers serve` hosting the same Hub model.
- `trust_remote_code` executes Python from the model repository. It stays off (`CADAI_LLM_TRUST_REMOTE_CODE=false`)
  unless a specific Hub commit is pinned in `CADAI_LLM_REVISION` and reviewed.
- The deterministic baseline planner (milestone 2) works without any LLM, so development and CI
  do not need the GPUs.

To verify at implementation time: the required `transformers` version and `trust_remote_code`
need; JSON-schema constrained-decoding support in the chosen backend; the chat template; and
whether V4-Pro accepts images. Visual QA needs a vision-capable model.

## Mock mode
Without SolidWorks, the compiler and a `MockDrawingExecutor` run; artifacts are watermarked and
labelled `generator: MOCK`. They are never presented as SolidWorks output.
