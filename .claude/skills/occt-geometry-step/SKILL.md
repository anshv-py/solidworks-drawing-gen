---
name: occt-geometry-step
description: Open Cascade Technology (OCCT) geometry engine work for CAD Drawing AI via the OCP Python bindings (cadquery-ocp). Activate when writing or reviewing code that imports STEP/STP (STEPControl_Reader, units), reads STL (RWStl), traverses B-Rep topology (TopoDS, TopExp, TopAbs), computes geometric properties (bounding box, volume, surface area, centroid, principal axes via GProp/BRepGProp), classifies faces (plane/cylinder/cone/sphere/torus via BRepAdaptor_Surface), determines edge convexity, recognizes features (holes, pockets, slots, bosses, fillets, chamfers, patterns), assigns stable feature/face IDs, tessellates for preview (BRepMesh), or builds GeometryIR. Do NOT use for drawing-content decisions (cad-engineering-automation) or SolidWorks (solidworks-api-automation).
---

# OCCT Geometry & STEP

OCCT is the **deterministic geometry engine**. Every number in GeometryIR is
computed here. An LLM never replaces these calculations.

## Binding

- Package: `cadquery-ocp` (module `OCP`), Apache-2.0 bindings; OCCT itself is
  LGPL-2.1 with the OCCT exception - dynamic linking via the wheel is fine for a
  proprietary service; do not statically link / modify OCCT without review.
- Version in use: **cadquery-ocp 8.0.1** (OCCT 8.0). Static methods carry an
  `_s` suffix (`BRepGProp.VolumeProperties_s`). OCCT 8 bindings expose NCollection
  types under `OCP.OCP.collections` (e.g.
  `IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher`) - the OCCT 7.x names
  `TopTools_IndexedMapOfShape` do **not** exist in this build. Isolate such
  version-specific imports in `geometry_service/occt/compat.py`.
- Verified calls: see `references/ocp-api-verified.md` (each probed in this
  environment). Anything else: probe with `dir()`/`__doc__` first and add it.

## Pipeline

```
validate file → import (STEP: STEPControl_Reader, mm) → heal/check (BRepCheck_Analyzer)
→ topology index (IndexedMap per type → F#/E#/V# indices)
→ properties (BRepGProp volume/surface, Bnd_Box, principal axes)
→ face classification (BRepAdaptor_Surface.GetType)
→ edge convexity (in-face probe points + BRepClass3d_SolidClassifier)
→ feature recognition (holes → bosses → pockets/slots → fillets/chamfers → patterns)
→ stable IDs (content hash) → GeometryIR (pydantic) → preview mesh (BRepMesh)
```

## Rules

1. **Units**: set reader system length unit to mm; record file units from
   `FileUnits`; GeometryIR is always mm/degrees.
2. **Tolerances are relative**: `eps = 1e-4 × bbox diagonal` for probes,
   `angle_tol = 0.5°` for parallelism, `length_tol = 1e-6 mm` rounding for
   hashes (round to 1e-4 mm before hashing).
3. **Deterministic ordering**: sort outputs by stable ID, never by Python
   `id()` or hash of OCCT objects.
4. **Stable IDs**: face signature = sha1(surface type + rounded params +
   rounded area + rounded centroid). Feature ID = `<TYPE>-` + first 8 hex of
   sha1(sorted member face signatures). Same file → same IDs; independent of
   traversal order. Topological indices (`F12`) are kept for debugging only.
5. **Associations**: every feature lists its `face_ids` (and edge IDs where
   relevant); every face lists `edge_ids` and `adjacent_face_ids`.
6. **Confidence**: analytic STEP recognition ≤ 1.0 with rule-specific values
   (e.g. full concave cylinder hole 0.99; heuristic chamfer 0.7); STL-derived
   values carry explicit lower confidence and `exact=false`.
7. **Untrusted input**: parsing runs in a subprocess with timeout and memory
   limit; malformed STEP can crash native code.
8. **Threads** are not recognisable from plain B-Rep; do not guess.

## References
- `references/ocp-api-verified.md` - verified OCP calls and gotchas
- `references/feature-recognition.md` - algorithms and confidence values
- `references/stl-handling.md` - mesh properties and limits
- `examples/hole_probe.py` - minimal hole-detection example (runs)
- `examples/geometry-ir-excerpt.json` - GeometryIR excerpt
