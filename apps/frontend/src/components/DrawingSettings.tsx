import type { DrawingDefaults } from "../lib/api";
import type { DrawingPlan } from "../generated/drawing-plan";

interface Props {
  defaults: DrawingDefaults;
  plan: DrawingPlan;
  onChange: (plan: DrawingPlan) => void;
}

function Select({ label, value, options, onChange }: {
  label: string; value: string; options: string[]; onChange: (v: string) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-2 text-sm">
      <span className="text-slate-600">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
        {options.map((o) => <option key={o} value={o}>{o.replaceAll("_", " ")}</option>)}
      </select>
    </label>
  );
}

const PICTORIAL = ["ISOMETRIC", "DIMETRIC", "TRIMETRIC"];

export default function DrawingSettings({ defaults, plan, onChange }: Props) {
  const o = defaults.options;
  const dims = plan.dimensions;
  return (
    <div className="space-y-2 rounded-lg bg-white p-3 shadow-sm" data-testid="drawing-settings">
      <p className="font-medium">Drawing settings</p>
      <Select label="Primary view" value={plan.primary_view.orientation} options={o.view_orientation ?? []}
        onChange={(v) => onChange({ ...plan, primary_view: { ...plan.primary_view, orientation: v as DrawingPlan["primary_view"]["orientation"], dimensioned: !PICTORIAL.includes(v) } })} />
      <Select label="Standard" value={plan.drawing_standard} options={o.drawing_standard ?? []}
        onChange={(v) => onChange({ ...plan, drawing_standard: v as DrawingPlan["drawing_standard"] })} />
      <Select label="Projection" value={plan.projection_method} options={o.projection_method ?? []}
        onChange={(v) => onChange({ ...plan, projection_method: v as DrawingPlan["projection_method"] })} />
      <Select label="Sheet" value={plan.sheet.size} options={o.sheet_size ?? []}
        onChange={(v) => onChange({ ...plan, sheet: { ...plan.sheet, size: v as DrawingPlan["sheet"]["size"] } })} />
      <Select label="Orientation" value={plan.sheet.orientation} options={o.sheet_orientation ?? []}
        onChange={(v) => onChange({ ...plan, sheet: { ...plan.sheet, orientation: v as DrawingPlan["sheet"]["orientation"] } })} />
      <Select label="Units" value={plan.units} options={o.units ?? []} onChange={() => undefined} />
      <fieldset className="grid grid-cols-2 gap-1 pt-1 text-sm">
        <legend className="mb-1 text-slate-600">Dimensions</legend>
        {(["overall", "feature", "holes", "radii", "diameters", "angles", "depths"] as const).map((k) => (
          <label key={k} className="flex items-center gap-1.5">
            <input type="checkbox" checked={dims[k]} onChange={(e) => onChange({ ...plan, dimensions: { ...dims, [k]: e.target.checked } })} />
            {k}
          </label>
        ))}
      </fieldset>
      <p className="rounded bg-slate-50 p-2 text-xs text-slate-600">
        Drawing type: <b>{plan.drawing_kind}</b>. Material, tolerances, GD&amp;T, datums and finish are
        <b> unspecified</b> and will not be invented.
      </p>
      <button type="button" disabled title="Drawing generation arrives in the next milestones"
        className="w-full rounded bg-slate-300 px-3 py-1.5 text-sm text-slate-600">
        Generate drawing (not available yet)
      </button>
    </div>
  );
}
