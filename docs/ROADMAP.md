# Roadmap

| # | Milestone | Status |
|---|---|---|
| 0 | Claude skills, project instructions, knowledge structure | ✅ done |
| 1 | STEP/STL → OCCT → GeometryIR → features → API → 3D preview | ✅ done, tested |
| 2 | Dimension candidates + deterministic planner + compiler + open-source executor (PDF/DXF/SVG) + deterministic QA/repair + API/UI | ✅ done, tested (no LLM) |
| 2b | User-supplied GD&T, datums, tolerances, threads, finish, notes, revisions; SolidWorks-style sheet format (zones, title block, notes, revision table); shaded isometric | ✅ done, tested |
| 2c | Default datums + ISO 2768-mK GD&T applied directly (reference-generator conventions), boxed TEDs, concise notes, user-selectable scales (sheet, isometric, ISO 5455 / intermediate series), isometric fixed top-right | ✅ done, tested |
| 3 | **Section & detail views** (turned parts, internal features) | ⏭ next |
| 4 | Better annotation layout (leader routing around geometry, ordinate dims option) | planned |
| 5 | Job system hardening: RQ runner, SSE progress, Alembic migrations, auth | planned |
| 6 | SolidWorks Windows worker (verified API, STA, leasing) → SLDDRW + DWG | planned |
| 7 | Visual QA (optional, only if a free local vision model proves useful) | planned |
| 8 | STL feature recognition + mesh drawings | planned |
| 9 | Evaluation against human reference drawings | planned |

## Next milestone (3) - exact scope
1. Section views: `SectionPlane` through a feature axis (turned parts: plane through the boss
   axis). OCCT cut by a half-space, hidden-line removal of the remaining half, and hatching of the
   faces lying in the cutting plane (DXF HATCH, ISO 128-50 45° lines). Section line and "A-A" labels.
2. Planner rule: use a full section as FRONT for axisymmetric parts with internal bores (like the
   reference flange drawing). Move internal-diameter dimensions into the section.
3. Detail views for features below a readable size at sheet scale.
4. Check the projection symbol's proportions against ISO 5456-2.
5. QA: section-line ↔ section-view consistency (QA-SEC-001), detail labels (QA-DET-001).

## Open questions / verification debt
- SolidWorks API signatures (register in the solidworks skill) - unverified.
- Docker image with `libgl1` not built in the sandbox (Debian mirror blocked).
