# Drawing QA (implemented - deterministic)

Loop: GENERATE → VALIDATE → REPAIR → VALIDATE. Up to `CADAI_QA_MAX_RETRIES` (default 3) extra
iterations. Repairs are compiler options: `REDUCE_SCALE` (next ISO 5455 step) and
`INCREASE_TIER_GAP`. If any **CRITICAL** issue remains, no PDF/DXF/SVG is exported. The job
ends `FAILED` with `QA_FAILED`, and only a diagnostic preview is kept.

Several checks compare two **independent** computations: the compiler's analytic projection of
GeometryIR, and OCCT's hidden-line output of the real B-Rep.

| Check | Severity | What |
|---|---|---|
| QA-SHEET-001/002 | CRITICAL | view geometry / dimensions inside the frame |
| QA-SHEET-003 | CRITICAL | nothing in the title-block/notes strip |
| QA-VIEW-001 | CRITICAL | views do not overlap |
| QA-VIEW-002 | CRITICAL | OCCT-drawn view extent == GeometryIR extent (catches wrong orientation or geometry) |
| QA-VIEW-003 | CRITICAL | placement matches first/third-angle projection |
| QA-VIEW-004 | MAJOR | ISO 5455 scale |
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
| QA-TB-001 | CRITICAL | no engineering data in the title block without a source |
| QA-REF-001 | CRITICAL | every dimension references a known candidate |

`POST /api/drawings/{id}/validate` re-runs the checks on the stored drawing (pure Python).
Visual (vision-model) QA is not implemented; no LLM is used.

Tests inject faults (a view drawn 10 % too wide, a tampered label, invented material,
overlapping views) and assert that QA catches each one.
