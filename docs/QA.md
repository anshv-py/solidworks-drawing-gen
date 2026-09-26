# Drawing QA (implemented - deterministic)

Loop: GENERATE → VALIDATE → REPAIR → VALIDATE. Up to `CADAI_QA_MAX_RETRIES` (default 3) extra
iterations. Repairs are compiler options: `REDUCE_SCALE` (next `DRAWING_SCALES` step) and
`INCREASE_TIER_GAP`. A repair must not make the drawing worse: the best iteration is kept (fewest
critical, then major issues, then the larger scale). If any **CRITICAL** issue remains, no PDF/DXF/SVG
is exported. The job ends `FAILED` with `QA_FAILED`, and only a diagnostic preview is kept.

**Compliance gate** (primary rule set, EX 1): after QA every drawing gets `compliance.json` with the 12
items of the Universal Mandatory Minimum (PASS / FAIL / WARN / N/A with details), the assumed roles and
the view triggers. Hard blockers 1-8 and 11 (title block incl. material, part number and revision;
general tolerance; default finish; datum frame; every feature dimensioned; no duplicates; full thread
designations; functional features toleranced; revision) stamp the sheet
"NOT FOR MANUFACTURE - INCOMPLETE" and make `POST /api/drawings/{id}/release` answer 409
`RELEASE_BLOCKED`. Warnings 9 (section / detail / auxiliary / break triggers), 10 (mixed standards) and
12 (weight) are reported.

Several checks compare two **independent** computations: the compiler's analytic projection of
GeometryIR, and OCCT's hidden-line output of the real B-Rep.

| Check | Severity | What |
|---|---|---|
| QA-SHEET-001/002 | CRITICAL | view geometry / dimensions inside the frame |
| QA-SHEET-003 | CRITICAL | no view, dimension or annotation touches the title block, `Note:` block, revision table or release stamp |
| QA-VIEW-001 | CRITICAL | views do not overlap |
| QA-VIEW-002 | CRITICAL | OCCT-drawn view extent == GeometryIR extent (catches wrong orientation or geometry); a section may be smaller, never larger |
| QA-VIEW-003 | CRITICAL | placement matches first/third-angle projection |
| QA-VIEW-004 | MAJOR / MINOR | supported drawing scale (MAJOR); intermediate, non-ISO 5455 scale (MINOR) |
| QA-VIEW-005 | MINOR | sheet fill ratio |
| QA-VIEW-006 | CRITICAL | a view produced no geometry |
| QA-DIM-001 | CRITICAL | label == GeometryIR value; sheet distance ÷ scale == value; overall dims == OCCT extents; leader tips touch drawn geometry |
| QA-DIM-002 | CRITICAL / MAJOR | planned dimension placed / overall dims present |
| QA-DIM-003 | CRITICAL | no duplicate dimensions |
| QA-DIM-004 | MAJOR | no redundant chains |
| QA-DIM-005 | MAJOR | dimension texts don't overlap each other or other views |
| QA-ANN-001 | MAJOR | every hole has a center mark in its circular view |
| QA-ANN-003 | MAJOR | every hole has a callout |
| QA-TXT-001 | MAJOR | text height ≥ 2.5 mm |
| QA-TB-001 | CRITICAL | every engineering value in the title block (material, tolerances, finish, edge note) was supplied by the user |
| QA-PMI-001 | CRITICAL / MAJOR | every user annotation was placed (UNPLACED → critical); crowded placement → major, repair `REDUCE_SCALE` |
| QA-PMI-002 | CRITICAL | each datum is shown exactly once. Frame count, datum references, tolerances, inspection marks and finish symbols all match what the user supplied |
| QA-DAT-003 | MAJOR / MINOR | datum feature form control missing (primary: major) or not tighter than what references it (rule 3) |
| QA-DAT-005 | MINOR | cast/forged/welded/moulded part: confirm datum features are machined or use datum targets (rules 5, 7) |
| QA-DAT-007 | MAJOR | sheet metal datum on a sheet edge (rule 7) |
| QA-DAT-008 | MAJOR | one datum feature used for two datums, or a frame referencing its own datum feature (rule 8) |
| QA-DAT-009 | MAJOR | datum not referenced by any frame (rule 9) |
| QA-TOL-001 | MAJOR | tolerance zone below 0.01 mm (not verifiable with standard shop equipment) |
| QA-NOTE-001 | MAJOR | default-note values not supplied (printed as placeholders) |
| QA-PMI-003 | MAJOR | frames, datum symbols and finish symbols don't overlap dimension text, each other or other views |
| QA-PMI-004 | CRITICAL | every feature control frame prints its planned tolerance exactly (no rounding to the drawing's decimals) |
| QA-SEC-001 | CRITICAL | every section view has hatched cut faces and its cutting plane (same letter) is shown in another view |
| QA-AUX-001 | CRITICAL | every auxiliary view has its lettered arrow in the view it was projected from (auxiliary views are exempt from the extent / alignment checks) |
| QA-FLAT-001 | CRITICAL | a planned flat pattern is on the sheet, drawn where its dimensions are, with one bend line per bend |
| QA-DET-001 | CRITICAL | every detail view shows geometry and its region is circled with the same letter in the view it enlarges (details are exempt from the extent / projection-alignment / centre-mark checks) |
| QA-REF-001 | CRITICAL | every dimension references a known candidate |

`POST /api/drawings/{id}/validate` re-runs the checks on the stored drawing (pure Python).
Visual (vision-model) QA is not implemented; no LLM is used.

Tests inject faults (a view drawn 10 % too wide, a tampered label, invented material,
overlapping views) and assert that QA catches each one.
