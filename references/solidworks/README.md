# SolidWorks API - official sources

| Source | URL | Access from build env (2026-09-24) |
|---|---|---|
| SOLIDWORKS API Help (per version) | https://help.solidworks.com/2026/english/api/sldworksapi/ | direct fetch **blocked** by egress proxy; reachable via web search snippets |
| IDrawingDoc members | https://help.solidworks.com/2024/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.idrawingdoc_methods.html | search index only |
| IModelDocExtension.SaveAs3 | https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~SaveAs3.html | search index only |
| Interop assemblies | `<SOLIDWORKS install>\api\redist\SolidWorks.Interop.*.dll` | on the Windows worker host |

Verification register (which members are confirmed, which are not):
`.claude/skills/solidworks-api-automation/references/api-verification.md`.
**Action before implementing the worker:** open each page on a machine with
access, for the installed SolidWorks version, and record the signatures.
