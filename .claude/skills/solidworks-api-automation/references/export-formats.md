# Export formats

| Format | Produced by | Notes |
|---|---|---|
| SLDDRW | IModelDocExtension.SaveAs3 on the drawing | Native; references the part - ship the part (.SLDPRT) alongside or pack-and-go |
| PDF | SaveAs3 with `.pdf` extension (+ export PDF data for sheet selection) | Vector; used for preview rasterization and visual QA |
| DWG | SaveAs3 with `.dwg` | Governed by SolidWorks DXF/DWG export options (version, font mapping, scale 1:1, sheet vs. model space). Set options explicitly per job; do not rely on user profile defaults |
| DXF | SaveAs3 with `.dxf` | Same options as DWG |

Post-export verification: file exists, size > 0, PDF parses, DXF/DWG header
readable (DXF via `ezdxf` on Linux side). Record the export option values used
in the op log for traceability.
