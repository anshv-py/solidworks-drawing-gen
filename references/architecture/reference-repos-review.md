# Review of the reference repositories (2026-09-24)

Both repos were cloned read-only and inspected; **no code was copied**.

## U-C4N/Autocad-MCP  (commit abc2a82, 2026-08-07)
- **Licence: MIT** - permissive; reuse possible with attribution, but nothing is reused today.
- Architecture: Python MCP server with two back-ends - AutoCAD COM (Windows) and
  `ezdxf` (headless DXF). Capability/tool registry, security tests, "ezdxf honesty"
  tests that refuse operations the headless backend can't really perform.
- Useful ideas: explicit capability refusal instead of faking results (mirrors our
  MOCK labelling rule); headless DXF backend for tests.
- Limitations for us: AutoCAD-centric, LLM drives low-level tool calls (we deliberately
  use a typed DrawingPlan + deterministic compiler instead).

## eyfel/mcp-server-solidworks ("SolidPilot")  (commit fc3c743, 2026-09-10)
- **Licence: AGPL-3.0** with a CLA enabling dual (commercial) licensing.
  → **Do not copy or link code** into CAD Drawing AI: AGPL network-use terms would
  apply to our service. Ideas only (not copyrightable) may inform design.
- Architecture: MCP adapter (Python) → CAD-neutral Feature Graph IR → deterministic
  compiler → C# .NET Framework 4.8 execution service (OWIN Web API) that is the only
  COM-touching layer; all COM calls marshalled onto one dedicated STA thread
  (`StaExecutor`), with an operation guard/idempotency layer.
- Drawing code uses members such as CreateDrawViewFromModelView3, CreateSectionViewAt5,
  InsertModelAnnotations3, AddHoleCallout2, GetFirstView/GetNextView - this is a
  *hint list* for our own verification, not a source of truth.
- Observations: reported STA requirement (off-STA calls returned null / deadlocked)
  corroborates our single-STA-thread worker design; targets SolidWorks 2026.
- Not production-ready for our use: single-process REST service without the job
  leasing, sandboxing, artifact verification and QA loop we require.
