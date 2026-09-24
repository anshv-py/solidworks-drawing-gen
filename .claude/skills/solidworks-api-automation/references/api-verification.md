# SolidWorks API members - verification register

Status meanings:
- **EXISTS-CONFIRMED** - member name confirmed to exist in official API help
  (help.solidworks.com index/search result) on 2026-09-24; **signature not yet
  checked** by us.
- **VERIFIED-SIGNATURE** - full parameter list checked against the official
  page for the target SolidWorks version. *(None yet - direct access to
  help.solidworks.com was blocked from the build environment; verify on a
  machine with access before implementing the worker.)*
- **UNVERIFIED** - believed to exist from general knowledge; must be checked.

| Interface.Member | Purpose | Status | Notes |
|---|---|---|---|
| IDrawingDoc.CreateDrawViewFromModelView3 | Place a named model view | EXISTS-CONFIRMED | Search snippet: args ModelName, ViewName, LocX, LocY, LocZ (meters) |
| IDrawingDoc.CreateUnfoldedViewAt3 | Projected view from selected view | EXISTS-CONFIRMED | 4 args (x, y, z, notAligned) per index snippet - verify |
| IDrawingDoc.CreateSectionViewAt5 | Section view | EXISTS-CONFIRMED (name) | Signature unverified |
| IDrawingDoc.CreateDetailViewAt4 | Detail view | UNVERIFIED | Search surfaced CreateDetailViewAt3; confirm which version is current |
| IDrawingDoc.InsertModelAnnotations3 | Import model dims/annotations into views | EXISTS-CONFIRMED | Signature unverified |
| IDrawingDoc.InsertCenterMark3 | Center mark | EXISTS-CONFIRMED | Signature unverified |
| IView.AutoInsertCenterMarks2 | Auto center marks in a view | EXISTS-CONFIRMED | Signature unverified |
| IDrawingDoc.AddHoleCallout2 | Hole callout | EXISTS-CONFIRMED (name) | Signature unverified |
| IDrawingDoc.GetFirstView / IView.GetNextView | View traversal (first = sheet) | UNVERIFIED | |
| IModelDocExtension.SaveAs3 | Save/export (SLDDRW, PDF, DWG, DXF) | EXISTS-CONFIRMED | Uses IAdvancedSaveAsOptions via GetAdvancedSaveAsOptions; STEP/STL/IGES export requires active doc |
| IModelDocExtension.SaveAs | Older save/export | EXISTS-CONFIRMED | Prefer SaveAs3 on recent versions |
| ISldWorks.NewDocument | New drawing from template | UNVERIFIED | |
| ISldWorks.LoadFile4 | Import STEP/STL | UNVERIFIED | |
| ISldWorks.OpenDoc6 | Open native docs | UNVERIFIED | |
| ISldWorks.CloseDoc | Close document | UNVERIFIED | |
| ISldWorks.GetUserPreferenceStringValue / SetUserPreference* | Import/export options | UNVERIFIED | |
| IModelDocExtension.SelectByID2 | Selection | UNVERIFIED | |
| IModelDoc2.AddDimension2 | Dimension selected entities | UNVERIFIED | |
| IView.GetOutline / GetPosition / Position | View bounds & placement (QA) | UNVERIFIED | |
| IExportPdfData (via GetExportFileData) | PDF export options | UNVERIFIED | |

Before implementing a row: open the official page for the installed version,
record signature + version here, and change status to VERIFIED-SIGNATURE.
