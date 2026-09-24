import { describe, expect, it } from "vitest";
import { MATERIAL_DEFAULT, MATERIAL_HIGHLIGHT, applyHighlight, buildEdges, buildGeometry } from "./mesh";
import type { PreviewMesh } from "./api";

const mesh: PreviewMesh = {
  format: "cad-drawing-ai/preview-mesh@1",
  units: "mm",
  positions: [0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0],
  indices: [0, 1, 2, 1, 3, 2],
  groups: [
    { face_id: "FACE-a", start: 0, count: 3 },
    { face_id: "FACE-b", start: 3, count: 3 },
  ],
  edges: [{ edge_id: "EDGE-1", points: [0, 0, 0, 1, 0, 0, 1, 1, 0] }],
};

describe("preview mesh", () => {
  it("creates one draw group per B-Rep face", () => {
    const g = buildGeometry(mesh, new Set(["FACE-b"]));
    expect(g.groups.map((x) => x.materialIndex)).toEqual([MATERIAL_DEFAULT, MATERIAL_HIGHLIGHT]);
    expect(g.boundingBox?.max.toArray()).toEqual([1, 1, 0]);
  });
  it("updates highlighting in place", () => {
    const g = buildGeometry(mesh);
    applyHighlight(g, mesh, new Set(["FACE-a"]));
    expect(g.groups.map((x) => x.materialIndex)).toEqual([MATERIAL_HIGHLIGHT, MATERIAL_DEFAULT]);
  });
  it("turns polylines into segment pairs", () => {
    expect(buildEdges(mesh).getAttribute("position").count).toBe(4);
  });
  it("handles STL meshes without face groups", () => {
    const g = buildGeometry({ ...mesh, groups: [] });
    expect(g.groups).toHaveLength(1);
  });
});
