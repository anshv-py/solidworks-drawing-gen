import type { GeometryIR } from "../generated/geometry-ir";
import type { DrawingPlan } from "../generated/drawing-plan";

export interface ModelOut {
  id: string;
  original_filename: string;
  format: "STEP" | "STL";
  size_bytes: number;
  sha256: string;
  status: "UPLOADED" | "ANALYZING" | "ANALYZED" | "FAILED";
  feature_count: number | null;
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
  plan: DrawingPlan;
  options: Record<string, string[]>;
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

export async function parseProblem(res: Response): Promise<ApiProblem> {
  try {
    const body = (await res.json()) as { code?: string; detail?: string };
    return new ApiProblem(res.status, body.code ?? `HTTP_${res.status}`, body.detail ?? res.statusText);
  } catch {
    return new ApiProblem(res.status, `HTTP_${res.status}`, res.statusText);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) throw await parseProblem(res);
  return (await res.json()) as T;
}

export const api = {
  upload(file: File): Promise<ModelOut> {
    const body = new FormData();
    body.append("file", file);
    return request("/api/models/upload", { method: "POST", body });
  },
  analyze: (modelId: string) =>
    request<{ job_id: string; job: JobOut }>(`/api/models/${modelId}/analyze`, { method: "POST" }),
  job: (jobId: string) => request<JobOut>(`/api/jobs/${jobId}`),
  model: (modelId: string) => request<ModelOut>(`/api/models/${modelId}`),
  geometry: (modelId: string) => request<GeometryIR>(`/api/models/${modelId}/geometry`),
  previewMesh: (modelId: string) => request<PreviewMesh>(`/api/models/${modelId}/preview-mesh`),
  drawingDefaults: () => request<DrawingDefaults>("/api/drawings/defaults"),
};

export const TERMINAL: JobState[] = ["COMPLETED", "FAILED"];
