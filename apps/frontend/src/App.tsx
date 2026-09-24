import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import DrawingSettings from "./components/DrawingSettings";
import FeatureTable from "./components/FeatureTable";
import GeometrySummary from "./components/GeometrySummary";
import JobProgress from "./components/JobProgress";
import UploadPanel from "./components/UploadPanel";
import type { DrawingPlan } from "./generated/drawing-plan";
import type { GeometryIR } from "./generated/geometry-ir";
import { useJob } from "./hooks";
import { ApiProblem, api, type DrawingDefaults, type ModelOut, type PreviewMesh } from "./lib/api";
import { highlightedFaces } from "./lib/features";

// three.js is large: load the viewer only when there is something to show
const ModelViewer = lazy(() => import("./components/ModelViewer"));

export default function App() {
  const [model, setModel] = useState<ModelOut | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [ir, setIr] = useState<GeometryIR | null>(null);
  const [mesh, setMesh] = useState<PreviewMesh | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [defaults, setDefaults] = useState<DrawingDefaults | null>(null);
  const [plan, setPlan] = useState<DrawingPlan | null>(null);
  const job = useJob(jobId);

  useEffect(() => {
    api.drawingDefaults().then((d) => { setDefaults(d); setPlan(d.plan); }).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (job?.state !== "COMPLETED" || !model) return;
    Promise.all([api.geometry(model.id), api.previewMesh(model.id)])
      .then(([g, m]) => { setIr(g); setMesh(m); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [job?.state, model]);

  const onFile = async (file: File) => {
    setError(null); setIr(null); setMesh(null); setSelected(null); setJobId(null);
    try {
      const m = await api.upload(file);
      setModel(m);
      const { job_id } = await api.analyze(m.id);
      setJobId(job_id);
    } catch (e) {
      setError(e instanceof ApiProblem ? `${e.code}: ${e.message}` : String(e));
    }
  };

  const highlighted = useMemo(() => (ir ? highlightedFaces(ir, selected) : new Set<string>()), [ir, selected]);
  const busy = job != null && job.state !== "COMPLETED" && job.state !== "FAILED";

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between bg-slate-900 px-4 py-2 text-white">
        <h1 className="font-semibold">CAD Drawing AI</h1>
        <span className="text-xs text-slate-400">Milestone 1 · STEP → OCCT → GeometryIR → features → preview</span>
      </header>
      <main className="grid min-h-0 flex-1 grid-cols-[340px_1fr_380px] gap-3 p-3">
        <aside className="space-y-3 overflow-y-auto">
          <UploadPanel disabled={busy} onFile={onFile} />
          {error && <p className="rounded bg-red-50 p-2 text-sm text-red-700" data-testid="error">{error}</p>}
          {job && <JobProgress job={job} />}
          {ir && <GeometrySummary ir={ir} />}
          {defaults && plan && <DrawingSettings defaults={defaults} plan={plan} onChange={setPlan} />}
        </aside>
        <section className="min-h-0 overflow-hidden rounded-lg bg-white shadow-sm">
          {mesh ? (
            <Suspense fallback={<div className="p-4 text-slate-400">Loading viewer…</div>}>
              <ModelViewer mesh={mesh} highlighted={highlighted} />
            </Suspense>
          ) : (
            <div className="flex h-full items-center justify-center text-slate-400">
              {busy ? "Analyzing geometry…" : "Upload a STEP or STL model to preview it"}
            </div>
          )}
        </section>
        <aside className="overflow-y-auto">
          {ir && <FeatureTable ir={ir} selected={selected} onSelect={setSelected} />}
        </aside>
      </main>
    </div>
  );
}
