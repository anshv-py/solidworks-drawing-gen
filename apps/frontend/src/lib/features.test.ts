import { describe, expect, it } from "vitest";
import { countByType, describeFeature, highlightedFaces, type Feature } from "./features";
import type { GeometryIR } from "../generated/geometry-ir";

const prov = { method: "test", exact: true };
const hole: Feature = {
  type: "HOLE", id: "HOLE-1", kind: "COUNTERBORE", diameter: 6.6, depth: 8, through: true,
  axis: { origin: [0, 0, 8], direction: [0, 0, -1] }, counterbore: { diameter: 11, depth: 4 }, countersink: null,
  confidence: 0.95, face_ids: ["FACE-a", "FACE-b"], edge_ids: [], provenance: prov, notes: [],
};
const pattern: Feature = {
  type: "PATTERN", id: "PAT-1", pattern_type: "CIRCULAR", member_feature_ids: ["HOLE-1"], member_type: "HOLE",
  count: 8, center: [0, 0, 0], axis_direction: [0, 0, 1], pitch_circle_diameter: 86, angular_step_deg: 45,
  directions: [], pitches: [], counts: [], confidence: 0.95, face_ids: ["FACE-a"], edge_ids: [], provenance: prov, notes: [],
};

describe("describeFeature", () => {
  it("formats a counterbored through hole from GeometryIR values", () => {
    expect(describeFeature(hole)).toBe("Ø6.60 THRU · ⌴ Ø11.00 ↧ 4.00");
  });
  it("formats a circular pattern", () => {
    expect(describeFeature(pattern)).toBe("8× circular on PCD Ø86.00, 45.0° step");
  });
});

describe("feature helpers", () => {
  const ir = { features: [hole, pattern] } as unknown as GeometryIR;
  it("highlights the faces of the selected feature", () => {
    expect([...highlightedFaces(ir, "HOLE-1")]).toEqual(["FACE-a", "FACE-b"]);
    expect(highlightedFaces(ir, null).size).toBe(0);
  });
  it("counts features by type", () => {
    expect(countByType(ir)).toEqual({ HOLE: 1, PATTERN: 1 });
  });
});
