import { useState } from "react";
import type { ComplianceReport } from "../generated/compliance-report";
import { ApiProblem, api, type DrawingOut } from "../lib/api";
import { ROLE_LABEL } from "./FeatureRoles";

const STATUS_STYLE: Record<string, string> = {
  PASS: "bg-emerald-100 text-emerald-800",
  FAIL: "bg-red-100 text-red-800",
  WARN: "bg-amber-100 text-amber-900",
  NOT_APPLICABLE: "bg-slate-100 text-slate-600",
};

/** Universal Mandatory Minimum of the primary rule set, assumed roles, and the explicit release step. */
export default function CompliancePanel({ drawing, onChange }: { drawing: DrawingOut; onChange: (d: DrawingOut) => void }) {
  const c: ComplianceReport | null = drawing.compliance;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!c) return null;
  const release = async () => {
    setBusy(true); setError(null);
    try {
      onChange(await api.release(drawing.id));
    } catch (e) {
      setError(e instanceof ApiProblem ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="rounded-lg bg-white p-3 text-sm shadow-sm" data-testid="compliance">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">Compliance ({c.rule_set})</span>
        {drawing.released ? (
          <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800" data-testid="released">
            Released {drawing.released_at?.slice(0, 10)}
          </span>
        ) : (
          <button type="button" onClick={release} disabled={busy || !drawing.passed} data-testid="release"
            className="rounded bg-emerald-600 px-3 py-1 text-xs text-white disabled:bg-slate-300 disabled:text-slate-600">
            Release for manufacture
          </button>
        )}
      </div>
      {c.stamp && (
        <p className="mt-2 rounded border border-red-300 bg-red-50 p-2 text-xs text-red-800" data-testid="stamp">
          Stamped “{c.stamp}”. The drawing can be downloaded, but it cannot be released until the failing
          hard blockers below are fixed.
        </p>
      )}
      {error && <p className="mt-2 rounded bg-red-50 p-2 text-xs text-red-700" data-testid="release-error">{error}</p>}
      <ul className="mt-2 space-y-1">
        {c.items.map((i) => (
          <li key={i.number} className="text-xs">
            <span className={`mr-1 inline-block w-12 rounded text-center ${STATUS_STYLE[i.status] ?? ""}`}>
              {i.status === "NOT_APPLICABLE" ? "N/A" : i.status}
            </span>
            {i.number}. {i.requirement}{i.hard_blocker ? "" : " (warning)"}
            {i.details.length > 0 && i.status !== "PASS" && (
              <span className="block pl-14 text-slate-500">{i.details.join(" · ")}</span>
            )}
          </li>
        ))}
      </ul>
      {c.assumed_roles.length > 0 && (
        <div className="mt-2 rounded bg-amber-50 p-2 text-xs" data-testid="assumed-roles">
          <p className="font-medium text-amber-900">Assumed roles – confirm or override under Manufacturing information</p>
          <ul className="mt-1 list-disc pl-4">
            {c.assumed_roles.map((a) => (
              <li key={a.target.feature_id ?? a.target.face_id ?? ""}>
                assumed role: <b>{ROLE_LABEL[a.role]}</b> – {a.description} ({Math.round(a.confidence * 100)}%, {a.rule})
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
