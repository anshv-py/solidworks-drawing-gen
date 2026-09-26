import type { RoleAssignment } from "../generated/compliance-report";
import type { DrawingSettings as Settings } from "../generated/drawing-settings";
import { targetKey } from "../lib/pmi";

type Role = RoleAssignment["role"];

export const ROLE_LABEL: Record<Role, string> = {
  MOUNTING_FACE: "Mounting face",
  SEALING_FACE: "Sealing face",
  BEARING_BORE: "Bearing bore",
  CENTRAL_BORE: "Central bore",
  BEARING_SEAT: "Bearing seat",
  SHOULDER_FACE: "Shoulder face",
  CLEARANCE_HOLES: "Clearance holes",
  DOWEL_HOLE: "Dowel hole",
  TAPPED_HOLE: "Tapped hole",
  KEYWAY: "Keyway",
  SEAL_GROOVE: "O-ring groove",
  NONE: "No functional role",
};
const FACE_ROLES: Role[] = ["MOUNTING_FACE", "SEALING_FACE", "SHOULDER_FACE", "NONE"];
const FEATURE_ROLES: Role[] = ["BEARING_BORE", "CENTRAL_BORE", "BEARING_SEAT", "CLEARANCE_HOLES", "DOWEL_HOLE",
  "TAPPED_HOLE", "KEYWAY", "SEAL_GROOVE", "NONE"];

interface Props {
  roles: RoleAssignment[];
  settings: Settings;
  onChange: (s: Settings) => void;
}

/** Functional roles decide which fits, GD&T and finish the rule set applies. Guesses are shown as
 * assumptions; confirming or changing one stores it by the feature's id, so it survives regeneration. */
export default function FeatureRoles({ roles, settings, onChange }: Props) {
  const setRole = (a: RoleAssignment, role: Role) => {
    const key = targetKey(a.target);
    const rest = settings.feature_roles.filter((o) => targetKey(o.target) !== key);
    onChange({ ...settings, feature_roles: [...rest, { target: a.target, role }] });
  };
  const reset = (a: RoleAssignment) => {
    const key = targetKey(a.target);
    onChange({ ...settings, feature_roles: settings.feature_roles.filter((o) => targetKey(o.target) !== key) });
  };
  if (!roles.length) {
    return <p className="text-xs text-slate-500">No functional roles recognised on this part.</p>;
  }
  return (
    <ul className="space-y-1.5" data-testid="feature-roles">
      {roles.map((a) => {
        const assumed = a.source === "INFERRED";
        return (
          <li key={targetKey(a.target)} className="rounded border border-slate-200 p-1.5 text-xs"
            data-testid={`role-${targetKey(a.target)}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="truncate" title={a.reasons.join("\n")}>{a.description}</span>
              <span className={`shrink-0 rounded px-1.5 ${assumed ? "bg-amber-100 text-amber-900" : "bg-emerald-100 text-emerald-800"}`}>
                {assumed ? `assumed · ${Math.round(a.confidence * 100)}%` : "confirmed"}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-1">
              <select className="flex-1 rounded border border-slate-300 px-1 py-0.5" value={a.role}
                onChange={(e) => setRole(a, e.target.value as Role)} data-testid="role-select">
                {(a.target.face_id ? FACE_ROLES : FEATURE_ROLES).map((r) => (
                  <option key={r} value={r}>{ROLE_LABEL[r]}</option>
                ))}
              </select>
              {assumed ? (
                <button type="button" onClick={() => setRole(a, a.role)} data-testid="role-confirm"
                  className="rounded border border-slate-300 px-2 py-0.5">Confirm</button>
              ) : (
                <button type="button" onClick={() => reset(a)} className="rounded border border-slate-300 px-2 py-0.5"
                  title="forget your choice and use the rule set's guess">Reset</button>
              )}
            </div>
            {assumed && <p className="mt-0.5 text-slate-500">{a.reasons[0]}</p>}
          </li>
        );
      })}
    </ul>
  );
}
