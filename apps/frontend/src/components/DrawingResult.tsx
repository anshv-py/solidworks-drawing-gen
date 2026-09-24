import type { DrawingOut } from "../lib/api";
import { downloadUrl, previewUrl } from "../lib/api";

const SEVERITY_STYLE: Record<string, string> = {
  CRITICAL: "bg-red-100 text-red-800",
  MAJOR: "bg-amber-100 text-amber-900",
  MINOR: "bg-slate-100 text-slate-700",
};

export default function DrawingResult({ drawing, onRegenerate }: { drawing: DrawingOut; onRegenerate: () => void }) {
  const qa = drawing.qa;
  const err = drawing.job.error;
  const qaRejected = err?.code === "QA_FAILED";
  // the job failed before QA could run (engine error, layout failure, crash): no preview, no QA
  const engineFailed = drawing.job.state === "FAILED" && !qaRejected;
  const title = drawing.passed ? "Drawing passed QA"
    : qaRejected ? "Drawing rejected by QA – exports blocked"
    : engineFailed ? "Drawing generation failed" : "Drawing not available";
  return (
    <div className="space-y-3" data-testid="drawing-result">
      {!engineFailed && (
        <div className="overflow-hidden rounded-lg bg-white shadow-sm">
          <img src={previewUrl(drawing.id, drawing.job.finished_at ?? "")} alt="Drawing preview"
            className="w-full" data-testid="drawing-preview" />
        </div>
      )}
      <div className="rounded-lg bg-white p-3 text-sm shadow-sm">
        <div className="flex items-center justify-between">
          <span className="font-medium">{title}</span>
          {qa && (
            <span className={`rounded px-2 py-0.5 text-xs ${drawing.passed ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>
              {`${qa.critical} critical · ${qa.major} major · ${qa.minor} minor`}
            </span>
          )}
        </div>
        {engineFailed && err && (
          <p className="mt-2 rounded bg-red-50 p-2 font-mono text-xs text-red-800" data-testid="drawing-error">
            {err.code}: {err.message}
          </p>
        )}
        {!engineFailed && (
          <p className="mt-1 text-xs text-slate-500">
            Scale {drawing.scale ?? "–"} · {drawing.generator} · {drawing.solidworks ? "SolidWorks" : "not a SolidWorks drawing"}
          </p>
        )}
        <div className="mt-2 flex flex-wrap gap-2">
          {drawing.downloads.map((fmt) => (
            <a key={fmt} href={downloadUrl(drawing.id, fmt)} data-testid={`download-${fmt}`}
              className="rounded bg-blue-600 px-3 py-1 text-white">{fmt.toUpperCase()}</a>
          ))}
          {Object.entries(drawing.unavailable_formats).map(([fmt, why]) => (
            <span key={fmt} title={why} className="cursor-help rounded bg-slate-200 px-3 py-1 text-slate-500">
              {fmt.toUpperCase()} (needs SolidWorks)
            </span>
          ))}
          <button type="button" onClick={onRegenerate} className="rounded border border-slate-300 px-3 py-1">
            Regenerate with current settings
          </button>
        </div>
        {qa && qa.issues.length > 0 && (
          <ul className="mt-3 space-y-1" data-testid="qa-issues">
            {qa.issues.map((i, k) => (
              <li key={k} className={`rounded px-2 py-1 text-xs ${SEVERITY_STYLE[i.severity] ?? ""}`}>
                <span className="font-mono">{i.check_id}</span> – {i.message}
              </li>
            ))}
          </ul>
        )}
        {qa && <p className="mt-2 text-xs text-slate-400">{qa.checks_run.length} deterministic checks run.</p>}
      </div>
    </div>
  );
}
