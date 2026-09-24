# drawing_executor

Open-source executor: OCCT hidden-line removal + ezdxf (DXF) + matplotlib (PDF/SVG/PNG), plus the
plan -> compile -> execute -> QA pipeline and its subprocess CLI:

```bash
python -m drawing_executor generate --geometry geometry_ir.json --source part.step \
  --settings settings.json --output-dir out/
```
Outputs are labelled as not produced by SolidWorks.
