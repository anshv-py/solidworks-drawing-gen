# Roadmap

| # | Milestone | Status |
|---|---|---|
| 0 | Claude skills, project instructions, knowledge structure | ✅ done |
| 1 | STEP/STL → OCCT → GeometryIR → features → API → 3D preview | ✅ done, tested |
| 2 | Dimension candidates + deterministic planner + compiler + open-source executor (PDF/DXF/SVG) + deterministic QA/repair + API/UI | ✅ done, tested (no LLM) |
| 2b | User-supplied GD&T, datums, tolerances, threads, finish, notes, revisions; SolidWorks-style sheet format (zones, title block, notes, revision table); shaded isometric | ✅ done, tested |
| 2c | Default datums + ISO 2768-mK GD&T applied directly (reference-generator conventions), boxed TEDs, concise notes, user-selectable scales (sheet, isometric, ISO 5455 / intermediate series), isometric fixed top-right | ✅ done, tested |
| R1 | **Primary rule set** (owner's RULES / EX documents): rule set as data, role inference + treatments (ISO 286 fits, GD&T, finish), minimum views, isometric only when triggered, view triggers, compliance report + NOT FOR MANUFACTURE stamp + release step, UI (roles, compliance, release) | ✅ done, tested |
| R1b | CAD metadata import: title, part number, revision, material, mass from STEP product data / AP214 user-defined attributes (custom properties) into the title block; calculated weight from volume × nominal density | ✅ done, tested (real SolidWorks exports UNVERIFIED) |
| 3 / R2 | **Section views** (RULES 1.3 triggers): full section in place of a view, OCCT cut + HLR, ISO 128-50 hatching, ISO 128-44 cutting plane + A-A, QA-SEC-001 | ✅ done, tested (half / multiple / offset sections: later) |
| R3 | **Detail views** (RULES 1.4 triggers at the final scale): enlarged circled regions placed in free space, QA-DET-001 | ✅ done, tested (dimensions inside details: later) |
| R4 | Tapped holes from tap-drill sizes (default callouts, blind depth = drill − 3P), keyways (N9), face O-ring grooves (recognizer + EX 6 treatment), sections never carry hidden features' dimensions | ✅ done, tested (radial grooves, modelled threads: later) |
| R5 | Auxiliary views (arrow method), shafts drawn horizontal, conventional breaks for long turned parts | ✅ done, tested (layout of horizontal-shaft annotations: long leaders - to improve) |
| R6 | Sheet-metal bends + DIN 6935 flat pattern view (EX 5) | ✅ done, tested (branched parts, reliefs: later) |
| R7 | New CAD version (`previous_model_id`) → automatic regeneration: feature diff, annotations / role overrides carried to the changed features, revision log, change report; UI "Upload new version" | ✅ done, tested |
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
