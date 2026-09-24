# Geometry drawing vs manufacturing drawing

A STEP/STL file (without PMI) defines **shape**. It does not define **intent**.

| Information | Derivable from B-Rep geometry? | Product behaviour when not supplied |
|---|---|---|
| Nominal sizes, positions, angles | Yes (STEP exact, STL inferred) | Use GeometryIR values |
| Material | No (unless STEP carries it and we parse it) | `UNSPECIFIED` |
| General tolerance class | No | `UNSPECIFIED` - do **not** default to ISO 2768-m |
| Individual tolerances / limits | No | none shown |
| GD&T frames | No (unless STEP AP242 semantic PMI is parsed) | none shown |
| Datum scheme | No | none; geometric references are not labelled as datums |
| Surface finish | No | `UNSPECIFIED` |
| Heat treatment / coating | No | `UNSPECIFIED` |
| Thread designation | Rarely (cosmetic threads) | plain cylinder dimensioned as Ø |
| Inspection requirements | No | `UNSPECIFIED` |
| Manufacturing process | No | `UNSPECIFIED` |

Every supplied value must record its **source** (`USER` or `CAD_MODEL`) so the
drawing is traceable. The title block for a geometry drawing should state that
tolerances/material are unspecified rather than leave blanks that look like
omissions.
