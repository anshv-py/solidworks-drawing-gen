# geometry_service

OCCT pipeline: STEP/STL → GeometryIR (+ preview mesh). Run as an isolated process:

```bash
python -m geometry_service analyze --input part.step --format STEP --output-dir out/
```
Emits JSON lines (`progress` / `result` / `error`) on stdout. See docs/GEOMETRY.md.
