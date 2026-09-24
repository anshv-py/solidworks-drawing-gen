import { describe, expect, it } from "vitest";
import { engField, faceLabel, parseTarget, targetKey } from "./pmi";

describe("pmi helpers", () => {
  it("blank means UNSPECIFIED, never an invented value", () => {
    expect(engField("  ")).toEqual({ status: "UNSPECIFIED", value: null, source: null });
    expect(engField(" AISI 304 ")).toEqual({ status: "SPECIFIED", value: "AISI 304", source: "USER" });
  });
  it("round-trips targets", () => {
    expect(parseTarget(targetKey({ face_id: "FACE-1", feature_id: null }))).toEqual({ face_id: "FACE-1", feature_id: null });
    expect(parseTarget("feature:HOLE-a")).toEqual({ face_id: null, feature_id: "HOLE-a" });
  });
  it("describes faces by direction and position", () => {
    expect(faceLabel({ id: "F", normal: [0, 0, -1], area: 7137.7, centroid: [0, 0, 0] }))
      .toBe("Planar face −Z at Z=0 (7138 mm²)");
  });
});
