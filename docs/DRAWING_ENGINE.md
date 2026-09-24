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
OpenAI Responses API with JSON-schema structured output of DrawingPlan; model configurable
(`CADAI_OPENAI_MODEL`, default `gpt-5.6-sol` - model id found in OpenAI's model documentation
index via web search on 2026-09-24; request parameters must be checked against the current
API reference at implementation time). Input: GeometryIR summary + candidate list + user settings.

## Mock mode
Without SolidWorks, the compiler and a `MockDrawingExecutor` run; artifacts are watermarked and
labelled `generator: MOCK`. They are never presented as SolidWorks output.
