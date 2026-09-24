# QA check catalogue - definitions

All coordinates in sheet millimetres, origin bottom-left of the sheet.

| Check | Inputs | Algorithm | Threshold (config key) |
|---|---|---|---|
| QA-SHEET-001/002 | sheet border rect, view/annotation bboxes | bbox ⊄ border inset | `qa.border_margin_mm` = 10 (ISO 5457 frame) |
| QA-SHEET-003 | title-block rect | rect intersection area > 0 | `qa.clearance_mm` = 2 |
| QA-VIEW-001 | view outlines | pairwise intersection with clearance | 2 mm |
| QA-VIEW-002 | manifest view orientation matrix vs plan | direction vectors dot > 0.999 | - |
| QA-VIEW-003 | parent/child view centres | first angle: TOP below FRONT, LEFT right of FRONT; third angle inverse | - |
| QA-VIEW-004 | view scale | ∈ ISO 5455 list and equals plan (unless AUTO) | - |
| QA-VIEW-005 | union area of view bboxes / drawable area | < ratio | `qa.min_fill_ratio` = 0.25 |
| QA-DIM-001 | dimension value, candidate value | abs diff > 0.5·10^-precision | display precision |
| QA-DIM-002 | required candidate set (policy) vs placed | set difference | policy file |
| QA-DIM-003 | candidate ids placed | count > 1 | - |
| QA-DIM-004 | per-axis chain graph | cycle detection over dimension graph | - |
| QA-DIM-005/ANN-004 | text/arrow bboxes | pairwise overlap | 1 mm |
| QA-ANN-001 | holes whose axis ∥ view direction | center mark present | - |
| QA-ANN-005 | text height | < min | `qa.min_text_height_mm` = 2.5 |
| QA-TB-001 | title-block fields | value present but source ∉ {USER, CAD_MODEL} | - |

Severity policy: CRITICAL blocks export; MAJOR triggers repair; MINOR is
reported only. Configurable per check in `qa-policy.yaml`.
