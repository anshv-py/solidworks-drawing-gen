# STL handling

- Read with `RWStl.ReadFile_s` (binary and ASCII) → `Poly_Triangulation`.
- STL has **no units**; assume mm and emit a warning `STL_UNITS_ASSUMED_MM`.
- Properties: bbox from nodes; area = Σ triangle areas; volume & centroid via
  signed tetrahedra (valid only if watertight & consistently oriented);
  principal axes from the triangle-mesh inertia tensor.
- Watertight check: every undirected edge used by exactly two triangles.
- Features: not recognized in milestone 1 (planned: region growing + RANSAC
  plane/cylinder fitting, reported with residuals and confidence).
- `representation = TESSELLATED`; every derived value `exact = false`.
