import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import DrawingResult from "./components/DrawingResult";
import DrawingSettings from "./components/DrawingSettings";
import FeatureTable from "./components/FeatureTable";
import GeometrySummary from "./components/GeometrySummary";
import JobProgress from "./components/JobProgress";
import UploadPanel from "./components/UploadPanel";
import type { DrawingSettings as Settings } from "./generated/drawing-settings";
import type { GeometryIR } from "./generated/geometry-ir";
import { useJob } from "./hooks";
import {
  ApiProblem,
  TERMINAL,
  api,
  type DrawingDefaults,
  type DrawingOut,
  type ModelOut,
  type PreviewMesh,
} from "./lib/api";
import { highlightedFaces } from "./lib/features";

// three.js is large: load the viewer only when there is something to show
const ModelViewer = lazy(() => import("./components/ModelViewer"));

const errorText = (e: unknown) => (e instanceof ApiProblem ? `${e.code}: ${e.message}` : String(e));

export default function App() {
  const [model, setModel] = useState<ModelOut | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [ir, setIr] = useState<GeometryIR | null>(null);
  const [mesh, setMesh] = useState<PreviewMesh | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [defaults, setDefaults] = useState<DrawingDefaults | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [drawingJobId, setDrawingJobId] = useState<string | null>(null);
  const [drawing, setDrawing] = useState<DrawingOut | null>(null);
  const [tab, setTab] = useState<"model" | "drawing">("model");
  const job = useJob(jobId);
  const drawingJob = useJob(drawingJobId);

  useEffect(() => {
    api.drawingDefaults().then((d) => { setDefaults(d); setSettings(d.settings); }).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (job?.state !== "COMPLETED" || !model) return;
    Promise.all([api.geometry(model.id), api.previewMesh(model.id)])
      .then(([g, m]) => { setIr(g); setMesh(m); })
      .catch((e: unknown) => setError(errorText(e)));
  }, [job?.state, model]);

  useEffect(() => {
    if (!drawingJobId || !drawingJob || !TERMINAL.includes(drawingJob.state)) return;
    api.drawing(drawingJobId).then((d) => { setDrawing(d); setTab("drawing"); }).catch(() => undefined);
  }, [drawingJobId, drawingJob]);

  const onFile = async (file: File) => {
    setError(null); setIr(null); setMesh(null); setSelected(null); setJobId(null);
    setDrawingJobId(null); setDrawing(null); setTab("model");
    try {
      const m = await api.upload(file);
      setModel(m);
      const { job_id } = await api.analyze(m.id);
      setJobId(job_id);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const onGenerate = async () => {
    if (!model || !settings) return;
    setError(null); setDrawing(null);
    try {
      const r = await api.generateDrawing(model.id, settings);
      setDrawingJobId(r.drawing_id);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const highlighted = useMemo(() => (ir ? highlightedFaces(ir, selected) : new Set<string>()), [ir, selected]);
  const busy = job != null && !TERMINAL.includes(job.state);
  const drawingBusy = drawingJob != null && !TERMINAL.includes(drawingJob.state);
  const stl = ir?.representation === "TESSELLATED";

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between bg-slate-900 px-4 py-2 text-white">
        <h1 className="font-semibold">CAD Drawing AI</h1>
        <span className="text-xs text-slate-400">
          STEP → OCCT → GeometryIR → deterministic plan → OCCT/ezdxf drawing → QA
        </span>
      </header>
      <main className="grid min-h-0 flex-1 grid-cols-[340px_1fr_380px] gap-3 p-3">
        <aside className="space-y-3 overflow-y-auto">
          <UploadPanel disabled={busy || drawingBusy} onFile={onFile} />
          {error && <p className="rounded bg-red-50 p-2 text-sm text-red-700" data-testid="error">{error}</p>}
          {job && <JobProgress job={job} />}
          {ir && <GeometrySummary ir={ir} />}
          {defaults && settings && (
            <DrawingSettings
              defaults={defaults} settings={settings} onChange={setSettings}
              canGenerate={ir != null && !stl} busy={drawingBusy} onGenerate={onGenerate}
              disabledReason={stl ? "Drawings need a STEP model (STL meshes are not supported yet)"
                : ir ? undefined : "Upload and analyze a model first"}
            />
          )}
          {drawingJob && <JobProgress job={drawingJob} />}
        </aside>
        <section className="flex min-h-0 flex-col overflow-hidden rounded-lg bg-white shadow-sm">
          {(drawing || drawingBusy) && (
            <div className="flex gap-1 border-b border-slate-200 p-1 text-sm">
              {(["model", "drawing"] as const).map((t) => (
                <button key={t} type="button" onClick={() => setTab(t)} data-testid={`tab-${t}`}
                  className={`rounded px-3 py-1 ${tab === t ? "bg-slate-900 text-white" : "hover:bg-slate-100"}`}>
                  {t === "model" ? "3D model" : "Drawing"}
                </button>
              ))}
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-auto">
            {tab === "drawing" && drawing ? (
              <div className="p-3"><DrawingResult drawing={drawing} onRegenerate={onGenerate} /></div>
            ) : tab === "drawing" ? (
              <div className="flex h-full items-center justify-center text-slate-400">Generating drawing…</div>
            ) : mesh ? (
              <Suspense fallback={<div className="p-4 text-slate-400">Loading viewer…</div>}>
                <ModelViewer mesh={mesh} highlighted={highlighted} />
              </Suspense>
            ) : (
              <div className="flex h-full items-center justify-center text-slate-400">
                {busy ? "Analyzing geometry…" : "Upload a STEP or STL model to preview it"}
              </div>
            )}
          </div>
        </section>
        <aside className="overflow-y-auto">
          {ir && <FeatureTable ir={ir} selected={selected} onSelect={setSelected} />}
        </aside>
      </main>
    </div>
  );
}
