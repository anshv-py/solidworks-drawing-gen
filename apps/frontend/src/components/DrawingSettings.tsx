import type { DrawingDefaults } from "../lib/api";
import type { DrawingSettings as Settings } from "../generated/drawing-settings";

interface Props {
  defaults: DrawingDefaults;
  settings: Settings;
  onChange: (s: Settings) => void;
  canGenerate: boolean;
  busy: boolean;
  onGenerate: () => void;
  disabledReason?: string;
}

function Select({ label, value, options, onChange, testId }: {
  label: string; value: string; options: string[]; onChange: (v: string) => void; testId?: string;
}) {
  return (
    <label className="flex items-center justify-between gap-2 text-sm">
      <span className="text-slate-600">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} data-testid={testId}
        className="rounded border border-slate-300 px-2 py-1">
        {options.map((o) => <option key={o} value={o}>{LABELS[o] ?? o.replaceAll("_", " ")}</option>)}
      </select>
    </label>
  );
}

const LABELS: Record<string, string> = {
  Z_UP: "Z up (Creo, NX, Inventor…)",
  Y_UP: "Y up (SolidWorks)",
  HIDDEN_LINES_VISIBLE: "hidden lines shown",
  HIDDEN_LINES_REMOVED: "hidden lines removed",
};

export default function DrawingSettings({ defaults, settings, onChange, canGenerate, busy, onGenerate, disabledReason }: Props) {
  const o = defaults.options;
  const dims = settings.dimensions;
  const set = (patch: Partial<Settings>) => onChange({ ...settings, ...patch });
  const ortho = o.orthographic_view ?? [];
  return (
    <div className="space-y-2 rounded-lg bg-white p-3 shadow-sm" data-testid="drawing-settings">
      <p className="font-medium">Drawing settings</p>
      <Select label="Primary view" value={settings.primary_view} options={o.view_orientation ?? []}
        onChange={(v) => set({ primary_view: v as Settings["primary_view"] })} />
      <Select label="Model up axis" value={settings.view_frame} options={o.view_frame ?? []}
        onChange={(v) => set({ view_frame: v as Settings["view_frame"] })} testId="view-frame" />
      <Select label="Standard" value={settings.drawing_standard} options={o.drawing_standard ?? []}
        onChange={(v) => set({ drawing_standard: v as Settings["drawing_standard"] })} />
      <Select label="Projection" value={settings.projection_method} options={o.projection_method ?? []}
        onChange={(v) => set({ projection_method: v as Settings["projection_method"] })} testId="projection" />
      <Select label="Sheet" value={settings.sheet.size} options={o.sheet_size ?? []}
        onChange={(v) => set({ sheet: { ...settings.sheet, size: v as Settings["sheet"]["size"] } })} />
      <Select label="Orientation" value={settings.sheet.orientation} options={o.sheet_orientation ?? []}
        onChange={(v) => set({ sheet: { ...settings.sheet, orientation: v as Settings["sheet"]["orientation"] } })} />
      <Select label="Orthographic views" value={settings.orthographic_display_style}
        options={["HIDDEN_LINES_VISIBLE", "HIDDEN_LINES_REMOVED"]}
        onChange={(v) => set({ orthographic_display_style: v as Settings["orthographic_display_style"] })} />
      <fieldset className="text-sm">
        <legend className="mb-1 text-slate-600">Projected views</legend>
        <div className="grid grid-cols-3 gap-1">
          {ortho.map((v) => (
            <label key={v} className="flex items-center gap-1.5">
              <input type="checkbox" checked={settings.projected_views.includes(v as never)}
                onChange={(e) => {
                  const next = e.target.checked
                    ? [...settings.projected_views, v as Settings["projected_views"][number]]
                    : settings.projected_views.filter((x) => x !== v);
                  if (next.length) set({ projected_views: next });
                }} />
              {v.toLowerCase()}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="grid grid-cols-2 gap-1 pt-1 text-sm">
        <legend className="mb-1 text-slate-600">Dimensions</legend>
        {(["overall", "feature", "holes", "radii", "diameters", "angles", "depths"] as const).map((k) => (
          <label key={k} className="flex items-center gap-1.5">
            <input type="checkbox" checked={dims[k]} onChange={(e) => set({ dimensions: { ...dims, [k]: e.target.checked } })} />
            {k}
          </label>
        ))}
      </fieldset>
      <p className="rounded bg-slate-50 p-2 text-xs text-slate-600">
        Drawing type: <b>{settings.drawing_kind}</b>. Material, tolerances, GD&amp;T, datums and finish are
        printed only when you enter them under <i>Manufacturing information</i>; otherwise they stay
        <b> unspecified</b> and are never invented.
      </p>
      <button type="button" disabled={!canGenerate || busy} onClick={onGenerate} title={disabledReason}
        data-testid="generate"
        className="w-full rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:bg-slate-300 disabled:text-slate-600">
        {busy ? "Generating…" : "Generate drawing"}
      </button>
      {!canGenerate && disabledReason && <p className="text-xs text-slate-500">{disabledReason}</p>}
    </div>
  );
}
