import type { GeometryIR } from "../generated/geometry-ir";

export type Feature = GeometryIR["features"][number];

/** Display precision only - values are GeometryIR measurements, never recomputed here. */
export const mm = (v: number, dp = 2): string => v.toFixed(dp);

export function describeFeature(f: Feature): string {
  switch (f.type) {
    case "HOLE": {
      let s = `Ø${mm(f.diameter)} ${f.through ? "THRU" : `↧ ${mm(f.depth)}`}`;
      if (f.counterbore) s += ` · ⌴ Ø${mm(f.counterbore.diameter)} ↧ ${mm(f.counterbore.depth)}`;
      if (f.countersink) s += ` · ⌵ Ø${mm(f.countersink.diameter)} × ${mm(f.countersink.angle_deg, 1)}°`;
      return s;
    }
    case "BOSS":
      return `Ø${mm(f.diameter)} × ${mm(f.height)}`;
    case "POCKET":
      return `${mm(f.length)} × ${mm(f.width)} ↧ ${mm(f.depth)}`;
    case "SLOT":
      return `${mm(f.width)} wide × ${mm(f.length)} long${f.through ? " THRU" : f.depth != null ? ` ↧ ${mm(f.depth)}` : ""}`;
    case "FILLET":
      return `R${mm(f.radius)} ${f.concave ? "(fillet)" : "(round)"}`;
    case "CHAMFER":
      return `${mm(f.distance_1)} × ${mm(f.distance_2)} (${mm(f.angle_deg, 1)}°)`;
    case "PATTERN":
      if (f.pattern_type === "CIRCULAR")
        return `${f.count}× circular on PCD Ø${mm(f.pitch_circle_diameter ?? 0)}, ${mm(f.angular_step_deg ?? 0, 1)}° step`;
      return `${f.count}× ${f.pattern_type.toLowerCase()} · pitch ${f.pitches.map((p) => mm(p)).join(" × ")}`;
    case "GROOVE":
      return `face groove Ø${mm(f.inner_diameter)}–Ø${mm(f.outer_diameter)} ↧ ${mm(f.depth)}`;
  }
}

/** Faces to highlight when a feature is selected (patterns highlight all member faces). */
export function highlightedFaces(ir: GeometryIR, featureId: string | null): Set<string> {
  if (!featureId) return new Set();
  const f = ir.features.find((x) => x.id === featureId);
  return new Set(f ? f.face_ids : []);
}

export function countByType(ir: GeometryIR): Record<string, number> {
  const out: Record<string, number> = {};
  for (const f of ir.features) out[f.type] = (out[f.type] ?? 0) + 1;
  return out;
}
