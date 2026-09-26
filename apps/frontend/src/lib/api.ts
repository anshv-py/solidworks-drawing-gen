import type { GeometryIR } from "../generated/geometry-ir";
import type { DrawingSettings } from "../generated/drawing-settings";
import type { ComplianceReport } from "../generated/compliance-report";
import type { QaReport } from "../generated/qa-report";
import type { AnnotationTargets } from "./pmi";

export interface ModelOut {
  id: string;
  original_filename: string;
  format: "STEP" | "STL";
  size_bytes: number;
  sha256: string;
  status: "UPLOADED" | "ANALYZING" | "ANALYZED" | "FAILED";
  feature_count: number | null;
  previous_model_id?: string | null;
  created_at: string;
}

export type JobState =
  | "QUEUED" | "ANALYZING" | "PLANNING" | "GENERATING" | "VALIDATING" | "EXPORTING" | "COMPLETED" | "FAILED";

export interface JobOut {
  id: string;
  kind: "ANALYZE" | "DRAWING";
  model_id: string;
  state: JobState;
  progress: number;
  message: string | null;
  error: { code: string; message: string } | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface PreviewMesh {
  format: string;
  units: "mm";
  positions: number[];
  indices: number[];
  groups: { face_id: string; start: number; count: number }[];
  edges: { edge_id: string; points: number[] }[];
}

export interface DrawingDefaults {
  settings: DrawingSettings;
  options: Record<string, string[]>;
}

export interface ChangeReport {
  previous_model_id: string;
  previous_drawing_id: string;
  revision: string;
  diff: { summary: string; added: string[]; removed: string[]; resized: string[][]; moved: string[][] };
  carried: string[];
  dropped: string[];
}

export interface DrawingOut {
  id: string;
  model_id: string;
  job: JobOut;
  settings: DrawingSettings;
  passed: boolean | null;
  scale: string | null;
  generator: string | null;
  solidworks: boolean;
  downloads: string[];
  unavailable_formats: Record<string, string>;
  qa: QaReport | null;
  compliance: ComplianceReport | null;
  change_report: ChangeReport | null;
  released: boolean;
  released_at: string | null;
}

/** RFC 9457 problem details returned by the API. */
export class ApiProblem extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    detail: string,
  ) {
    super(detail);
  }
}

/** The server no longer has this model / job / drawing - e.g. a host without a persistent disk
 * restarted and lost its data. */
export const isGone = (e: unknown): boolean => e instanceof ApiProblem && e.status === 404;

export async function parseProblem(res: Response): Promise<ApiProblem> {
  try {
    const body = (await res.json()) as { code?: string; detail?: unknown };
    return new ApiProblem(res.status, body.code ?? `HTTP_${res.status}`, problemText(body.detail) || res.statusText);
  } catch {
    return new ApiProblem(res.status, `HTTP_${res.status}`, res.statusText);
  }
}

/** FastAPI validation errors carry a list of {loc, msg}; show them as readable text. */
export function problemText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d: { loc?: unknown[]; msg?: string }) =>
      `${(d.loc ?? []).filter((x) => x !== "body").join(".")}: ${d.msg ?? ""}`).join("; ");
  }
  return detail == null ? "" : JSON.stringify(detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) throw await parseProblem(res);
  return (await res.json()) as T;
}

export const api = {
  upload(file: File, previousModelId?: string): Promise<ModelOut> {
    const body = new FormData();
    body.append("file", file);
    if (previousModelId) body.append("previous_model_id", previousModelId);
    return request("/api/models/upload", { method: "POST", body });
  },
  modelDrawings: (modelId: string) => request<JobOut[]>(`/api/models/${modelId}/drawings`),
  analyze: (modelId: string) =>
    request<{ job_id: string; job: JobOut }>(`/api/models/${modelId}/analyze`, { method: "POST" }),
  job: (jobId: string) => request<JobOut>(`/api/jobs/${jobId}`),
  model: (modelId: string) => request<ModelOut>(`/api/models/${modelId}`),
  geometry: (modelId: string) => request<GeometryIR>(`/api/models/${modelId}/geometry`),
  previewMesh: (modelId: string) => request<PreviewMesh>(`/api/models/${modelId}/preview-mesh`),
  drawingDefaults: () => request<DrawingDefaults>("/api/drawings/defaults"),
  generateDrawing: (modelId: string, settings: DrawingSettings) =>
    request<{ drawing_id: string; job: JobOut }>("/api/drawings/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId, settings }),
    }),
  annotationTargets: (modelId: string, settings: DrawingSettings) =>
    request<AnnotationTargets>("/api/drawings/annotation-targets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId, settings }),
    }),
  drawing: (drawingId: string) => request<DrawingOut>(`/api/drawings/${drawingId}`),
  release: (drawingId: string) => request<DrawingOut>(`/api/drawings/${drawingId}/release`, { method: "POST" }),
};

export const TERMINAL: JobState[] = ["COMPLETED", "FAILED"];

export const previewUrl = (jobId: string, bust = ""): string => `/api/jobs/${jobId}/preview${bust ? `?v=${bust}` : ""}`;
export const downloadUrl = (jobId: string, fmt: string): string => `/api/jobs/${jobId}/download/${fmt}`;
