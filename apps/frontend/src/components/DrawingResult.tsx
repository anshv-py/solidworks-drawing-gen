import type { DrawingOut } from "../lib/api";
import { downloadUrl, previewUrl } from "../lib/api";

const SEVERITY_STYLE: Record<string, string> = {
  CRITICAL: "bg-red-100 text-red-800",
  MAJOR: "bg-amber-100 text-amber-900",
  MINOR: "bg-slate-100 text-slate-700",
};

export default function DrawingResult({ drawing, onRegenerate }: { drawing: DrawingOut; onRegenerate: () => void }) {
  const qa = drawing.qa;
  return (
    <div className="space-y-3" data-testid="drawing-result">
      <div className="overflow-hidden rounded-lg bg-white shadow-sm">
        <img src={previewUrl(drawing.id, drawing.job.finished_at ?? "")} alt="Drawing preview"
          className="w-full" data-testid="drawing-preview" />
      </div>
      <div className="rounded-lg bg-white p-3 text-sm shadow-sm">
        <div className="flex items-center justify-between">
          <span className="font-medium">
            {drawing.passed ? "Drawing passed QA" : "Drawing rejected by QA – exports blocked"}
          </span>
          <span className={`rounded px-2 py-0.5 text-xs ${drawing.passed ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>
            {qa ? `${qa.critical} critical · ${qa.major} major · ${qa.minor} minor` : "no QA"}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          Scale {drawing.scale ?? "–"} · {drawing.generator} · {drawing.solidworks ? "SolidWorks" : "not a SolidWorks drawing"}
        </p>
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
