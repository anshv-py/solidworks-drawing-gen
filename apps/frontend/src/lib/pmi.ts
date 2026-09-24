// Helpers for the "Manufacturing information" form. Everything the form produces is entered by
// the user and references ids that exist in the part's GeometryIR / plan (the API re-validates).
import type { EngineeringField, Target } from "../generated/drawing-settings";

export interface AnnotationTargets {
  dimensions: { id: string; text: string; kind: string }[];
  planar_faces: { id: string; normal: [number, number, number] | null; area: number; centroid: [number, number, number] }[];
  features: { id: string; type: string; diameter: number | null }[];
}

/** A blank input means UNSPECIFIED; anything typed is SPECIFIED by the user. */
export function engField(value: string): EngineeringField {
  const v = value.trim();
  return v ? { status: "SPECIFIED", value: v, source: "USER" } : { status: "UNSPECIFIED", value: null, source: null };
}

export const targetKey = (t: Target | null | undefined): string =>
  t?.face_id ? `face:${t.face_id}` : t?.feature_id ? `feature:${t.feature_id}` : "";

export function parseTarget(key: string): Target {
  const [kind, id] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
  return kind === "face" ? { face_id: id, feature_id: null } : { face_id: null, feature_id: id };
}

const AXES = ["X", "Y", "Z"];

/** "Planar face +Z at Z=40 (1276 mm²)" - normal direction and position, so users can find it. */
export function faceLabel(f: AnnotationTargets["planar_faces"][number]): string {
  const n = f.normal ?? [0, 0, 0];
  const k = n.findIndex((c) => Math.abs(Math.abs(c) - 1) < 1e-6);
  if (k < 0) return `Planar face (inclined) ${f.area.toFixed(0)} mm² · ${f.id}`;
  const pos = Math.round((f.centroid[k] ?? 0) * 1000) / 1000;
  return `Planar face ${(n[k] ?? 0) > 0 ? "+" : "−"}${AXES[k]} at ${AXES[k]}=${pos} (${f.area.toFixed(0)} mm²)`;
}

export function featureLabel(f: AnnotationTargets["features"][number]): string {
  return `${f.type}${f.diameter ? ` Ø${f.diameter}` : ""} · ${f.id}`;
}

export const GDT: Record<string, string> = {
  STRAIGHTNESS: "⏤ straightness", FLATNESS: "⏥ flatness", CIRCULARITY: "○ circularity",
  CYLINDRICITY: "⌭ cylindricity", PROFILE_OF_A_LINE: "⌒ profile of a line", PROFILE_OF_A_SURFACE: "⌓ profile of a surface",
  ANGULARITY: "∠ angularity", PERPENDICULARITY: "⊥ perpendicularity", PARALLELISM: "∥ parallelism",
  POSITION: "⌖ position", CONCENTRICITY: "◎ concentricity", SYMMETRY: "⌯ symmetry",
  CIRCULAR_RUNOUT: "↗ circular runout", TOTAL_RUNOUT: "⌰ total runout",
};
// mirrors drawing_schema.pmi (the API enforces the same grammar)
export const FORM = ["STRAIGHTNESS", "FLATNESS", "CIRCULARITY", "CYLINDRICITY"];
export const NEEDS_DATUM = ["ANGULARITY", "PERPENDICULARITY", "PARALLELISM", "CONCENTRICITY", "SYMMETRY",
  "CIRCULAR_RUNOUT", "TOTAL_RUNOUT"];
export const DATUM_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ".split("");
