import { useEffect, useState } from "react";
import FeatureRoles from "./FeatureRoles";
import type {
  DatumReference,
  GeneralNotes,
  DrawingSettings as Settings,
  EngineeringInformation,
  ManufacturingAnnotations,
  TitleBlock,
} from "../generated/drawing-settings";
import { api, isGone } from "../lib/api";
import {
  type AnnotationTargets,
  DATUM_LETTERS,
  FORM,
  GDT,
  NEEDS_DATUM,
  engField,
  faceLabel,
  featureLabel,
  parseTarget,
  targetKey,
} from "../lib/pmi";

interface Props {
  modelId: string;
  settings: Settings;
  onChange: (s: Settings) => void;
  /** called when the server no longer has the model (it restarted without persistent storage) */
  onModelLost?: () => void;
}

const PROCESSES: GeneralNotes["process"][] = ["UNSPECIFIED", "CNC_MACHINED", "SHEET_METAL", "CASTING", "FORGING",
  "WELDMENT", "MOULDED", "ADDITIVE"];
const EMPTY: ManufacturingAnnotations = {
  datums: [], frames: [], tolerances: [], threads: [], inspection_dimensions: [], surface_finish_marks: [],
  feature_notes: [], notes: [], revisions: [], deburr_break_sharp_edges: false, basic_dimensions: [],
};
const input = "w-full rounded border border-slate-300 px-1.5 py-0.5 text-sm";
const small = "rounded border border-slate-300 px-1 py-0.5 text-sm";

function Text({ label, value, onChange, testId }: {
  label: string; value: string | null | undefined; onChange: (v: string) => void; testId?: string;
}) {
  return (
    <label className="grid grid-cols-[110px_1fr] items-center gap-1 text-sm">
      <span className="text-slate-600">{label}</span>
      <input className={input} value={value ?? ""} onChange={(e) => onChange(e.target.value)} data-testid={testId} />
    </label>
  );
}

function Section({ title, children, count }: { title: string; children: React.ReactNode; count?: number }) {
  return (
    <details className="rounded border border-slate-200 p-2">
      <summary className="cursor-pointer text-sm font-medium">
        {title}{count ? <span className="ml-1 text-xs text-slate-500">({count})</span> : null}
      </summary>
      <div className="mt-2 space-y-1.5">{children}</div>
    </details>
  );
}

function Remove({ onClick }: { onClick: () => void }) {
  return <button type="button" onClick={onClick} className="px-1 text-red-600" title="remove">✕</button>;
}

function Add({ onClick, children, disabled }: { onClick: () => void; children: React.ReactNode; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className="rounded border border-slate-300 px-2 py-0.5 text-xs disabled:opacity-40">+ {children}</button>
  );
}

export default function ManufacturingForm({ modelId, settings, onChange, onModelLost }: Props) {
  const [targets, setTargets] = useState<AnnotationTargets | null>(null);
  const [error, setError] = useState<string | null>(null);
  // the dimensions on the sheet depend on the view/dimension settings, not on the annotations
  // (the process steers the datum suggestion; other note fields do not affect the lookup)
  const planKey = JSON.stringify({ ...settings, manufacturing: null, title_block: null, engineering_information: null,
    drawing_kind: null, general_notes: settings.general_notes.process });
  useEffect(() => {
    let live = true;
    // incomplete rows being edited must not affect (or invalidate) the target lookup
    // (drawing kind / engineering data do not change which dimensions are placed)
    api.annotationTargets(modelId, { ...settings, drawing_kind: "GEOMETRY", manufacturing: EMPTY })
      .then((t) => { if (live) { setTargets(t); setError(null); } })
      .catch((e: Error) => {
        if (!live) return;
        if (isGone(e) && onModelLost) onModelLost(); // the server lost the model: the app re-uploads it
        else setError(e.message);
      });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelId, planKey]);

  const m = settings.manufacturing;
  const tb = settings.title_block;
  const info = settings.engineering_information;
  const setM = (patch: Partial<ManufacturingAnnotations>) => onChange({ ...settings, manufacturing: { ...m, ...patch } });
  const setTb = (patch: Partial<TitleBlock>) => onChange({ ...settings, title_block: { ...tb, ...patch } });
  const setInfo = (k: keyof EngineeringInformation, v: string) =>
    onChange({ ...settings, engineering_information: { ...info, [k]: engField(v) } });
  const g = settings.general_notes;
  const setG = (patch: Partial<GeneralNotes>) => onChange({ ...settings, general_notes: { ...g, ...patch } });
  const asme = settings.drawing_standard === "ASME";
  const letters = m.datums.map((d) => d.letter);
  const freeLetter = DATUM_LETTERS.find((l) => !letters.includes(l)) ?? "A";

  const targetOptions = (faces = true, features = true) => (
    <>
      <option value="">— select —</option>
      {faces && targets?.planar_faces.map((f) => <option key={f.id} value={`face:${f.id}`}>{faceLabel(f)}</option>)}
      {features && targets?.features.map((f) => <option key={f.id} value={`feature:${f.id}`}>{featureLabel(f)}</option>)}
    </>
  );
  const dimOptions = (
    <>
      <option value="">— select dimension —</option>
      {targets?.dimensions.map((d) => (
        <option key={d.id} value={d.id}>{d.text.replace("\n", " ")} · {d.id}</option>
      ))}
    </>
  );
  const replace = <T,>(arr: T[], i: number, v: T): T[] => arr.map((x, k) => (k === i ? v : x));

  return (
    <div className="space-y-2 rounded-lg bg-white p-3 shadow-sm" data-testid="manufacturing-form">
      <p className="font-medium">Manufacturing information</p>
      <p className="text-xs text-slate-600">
        Everything here is entered by you and printed exactly as entered; blank fields stay <b>UNSPECIFIED</b>.
        Only the feature roles below are guessed from the model - confirm or change them.
      </p>
      {error && <p className="rounded bg-red-50 p-1 text-xs text-red-700">{error}</p>}
      <label className="flex items-center justify-between text-sm">
        <span className="text-slate-600">Drawing type</span>
        <select className={small} value={settings.drawing_kind} data-testid="drawing-kind"
          onChange={(e) => onChange({ ...settings, drawing_kind: e.target.value as Settings["drawing_kind"] })}>
          <option value="GEOMETRY">Geometry drawing</option>
          <option value="MANUFACTURING">Manufacturing drawing</option>
        </select>
      </label>
      {settings.drawing_kind === "MANUFACTURING" &&
        <p className="text-xs text-slate-500">A manufacturing drawing needs a material and a general or linear tolerance.</p>}

      <Section title={`Feature roles${targets?.rule_set ? ` (${targets.rule_set})` : ""}`}
        count={targets?.roles?.filter((a) => a.source === "INFERRED").length}>
        <FeatureRoles roles={targets?.roles ?? []} settings={settings} onChange={onChange} />
      </Section>
      <Section title="Title block">
        <Text label="Title" value={tb.title} onChange={(v) => setTb({ title: v || null })} testId="tb-title" />
        <Text label="Drawing no." value={tb.drawing_number} onChange={(v) => setTb({ drawing_number: v || null })} />
        <Text label="Part no." value={tb.part_number} onChange={(v) => setTb({ part_number: v || null })} />
        <Text label="Revision" value={tb.revision} onChange={(v) => setTb({ revision: v.slice(0, 4) || null })} />
        <Text label="Company" value={tb.organization} onChange={(v) => setTb({ organization: v || null })} />
        <Text label="Weight" value={tb.weight} onChange={(v) => setTb({ weight: v || null })} />
        <Text label="Quantity" value={tb.quantity} onChange={(v) => setTb({ quantity: v || null })} />
        <div className="grid grid-cols-[60px_1fr_90px] gap-1 pt-1 text-xs text-slate-500">
          <span />
          <span>name</span>
          <span>date</span>
        </div>
        {(["drawn", "checked", "approved", "mfg", "qa"] as const).map((r) => (
          <div key={r} className="grid grid-cols-[60px_1fr_90px] items-center gap-1 text-sm">
            <span className="text-slate-600">{r === "qa" ? "Q.A" : r}</span>
            <input className={input} value={tb[`${r}_by`] ?? ""} onChange={(e) => setTb({ [`${r}_by`]: e.target.value || null })} />
            <input className={input} value={tb[`${r}_date`] ?? ""} onChange={(e) => setTb({ [`${r}_date`]: e.target.value || null })} />
          </div>
        ))}
      </Section>

      <Section title="Material, tolerances, finish">
        <Text label="Material" value={info.material.value} onChange={(v) => setInfo("material", v)} testId="material" />
        <Text label="General tol." value={info.general_tolerance.value} onChange={(v) => setInfo("general_tolerance", v)}
          testId="general-tol" />
        <Text label="Linear tol." value={info.linear_tolerance.value} onChange={(v) => setInfo("linear_tolerance", v)} />
        <Text label="Angular tol." value={info.angular_tolerance.value} onChange={(v) => setInfo("angular_tolerance", v)} />
        <Text label="Surface finish" value={info.surface_finish.value} onChange={(v) => setInfo("surface_finish", v)} />
        <Text label="Coating" value={info.coating.value} onChange={(v) => setInfo("coating", v)} />
        <Text label="Heat treatment" value={info.heat_treatment.value} onChange={(v) => setInfo("heat_treatment", v)} />
        <label className="flex items-center gap-1.5 text-sm">
          <input type="checkbox" checked={m.deburr_break_sharp_edges}
            onChange={(e) => setM({ deburr_break_sharp_edges: e.target.checked })} />
          print “DEBURR AND BREAK SHARP EDGES”
        </label>
      </Section>

      <Section title="Drawing notes (defaults)">
        <label className="flex items-center gap-1.5 text-sm">
          <input type="checkbox" checked={g.enabled} onChange={(e) => setG({ enabled: e.target.checked })}
            data-testid="notes-enabled" />
          print the 15 standard notes (anything not entered prints as [PLACEHOLDER])
        </label>
        <label className="grid grid-cols-[110px_1fr] items-center gap-1 text-sm">
          <span className="text-slate-600">Process</span>
          <select className={small} value={g.process} onChange={(e) => setG({ process: e.target.value as GeneralNotes["process"] })}>
            {PROCESSES.map((p) => <option key={p} value={p}>{p.replaceAll("_", " ").toLowerCase()}</option>)}
          </select>
        </label>
        <Text label="General geo. tol." value={g.general_geometric_tolerance}
          onChange={(v) => setG({ general_geometric_tolerance: v || null })} />
        <Text label="Edge break" value={g.edge_break} onChange={(v) => setG({ edge_break: v || null })} />
        <Text label="Masked surfaces" value={g.masked_surfaces} onChange={(v) => setG({ masked_surfaces: v || null })} />
        <Text label="Thread class" value={g.thread_class} onChange={(v) => setG({ thread_class: v || null })} />
        <Text label="Process sequence" value={g.process_sequence} onChange={(v) => setG({ process_sequence: v || null })} />
        <Text label="Model revision" value={g.model_revision} onChange={(v) => setG({ model_revision: v || null })} />
        <Text label="Inspection" value={info.inspection_requirements.value}
          onChange={(v) => setInfo("inspection_requirements", v)} />
        <Text label="Marking" value={g.marking} onChange={(v) => setG({ marking: v || null })} />
        <label className="flex items-center gap-1.5 text-sm">
          <input type="checkbox" checked={g.supplier_bullets} onChange={(e) => setG({ supplier_bullets: e.target.checked })} />
          “What the supplier must not assume”
        </label>
      </Section>

      <Section title="Datums" count={m.datums.length}>
        <label className="flex items-start gap-1.5 rounded border border-blue-200 bg-blue-50 p-1.5 text-xs">
          <input type="checkbox" data-testid="default-gdt" checked={settings.default_gdt}
            onChange={(e) => onChange({ ...settings, default_gdt: e.target.checked })} />
          <span>
            <b>Default datums &amp; GD&amp;T</b> - applied automatically when none are entered below: datum
            reference frame on the part's reference faces / axis, flatness, perpendicularity or run-out,
            and hole positions with boxed (TED) locations, all from ISO 2768-mK. Entering your own datums
            or frames replaces them.
          </span>
        </label>
        {m.datums.map((d, i) => (
          <div key={i} className="flex items-center gap-1">
            <select className={small} value={d.letter}
              onChange={(e) => setM({ datums: replace(m.datums, i, { ...d, letter: e.target.value }) })}>
              {DATUM_LETTERS.map((l) => <option key={l} disabled={l !== d.letter && letters.includes(l)}>{l}</option>)}
            </select>
            <select className={`${small} min-w-0 flex-1`} value={targetKey(d.target)}
              onChange={(e) => setM({ datums: replace(m.datums, i, { ...d, target: parseTarget(e.target.value) }) })}>
              {targetOptions()}
            </select>
            <Remove onClick={() => setM({ datums: m.datums.filter((_, k) => k !== i) })} />
          </div>
        ))}
        <Add disabled={!targets} onClick={() => setM({ datums: [...m.datums, { letter: freeLetter, target: { face_id: null, feature_id: null } }] })}>
          datum
        </Add>
      </Section>

      <Section title="GD&T feature control frames" count={m.frames.length}>
        {m.frames.map((f, i) => {
          const set = (patch: Partial<typeof f>) => setM({ frames: replace(m.frames, i, { ...f, ...patch }) });
          const form = FORM.includes(f.characteristic);
          return (
            <div key={i} className="space-y-1 rounded bg-slate-50 p-1.5">
              <div className="flex items-center gap-1">
                <select className={`${small} flex-1`} value={f.characteristic}
                  onChange={(e) => set({ characteristic: e.target.value as typeof f.characteristic,
                    datums: FORM.includes(e.target.value) ? [] : f.datums })}>
                  {Object.entries(GDT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                <label className="flex items-center gap-0.5 text-sm" title="diameter (Ø) tolerance zone">
                  <input type="checkbox" checked={f.diameter_zone} onChange={(e) => set({ diameter_zone: e.target.checked })} />Ø
                </label>
                <input className={`${small} w-16`} type="number" step="0.001" min="0" value={f.tolerance}
                  onChange={(e) => set({ tolerance: Number(e.target.value) })} />
                <select className={small} value={f.material_condition ?? ""}
                  onChange={(e) => set({ material_condition: (e.target.value || null) as typeof f.material_condition })}>
                  <option value="">RFS</option><option value="MMC">Ⓜ MMC</option><option value="LMC">Ⓛ LMC</option>
                </select>
                <Remove onClick={() => setM({ frames: m.frames.filter((_, k) => k !== i) })} />
              </div>
              <select className={`${small} w-full`} value={targetKey(f.target)}
                onChange={(e) => set({ target: parseTarget(e.target.value) })}>{targetOptions()}</select>
              {!form && (
                <div className="flex items-center gap-1 text-sm">
                  <span className="text-slate-600">datums</span>
                  {[0, 1, 2].map((k) => (
                    <select key={k} className={small} value={f.datums[k]?.letter ?? ""}
                      onChange={(e) => {
                        const next: DatumReference[] = [...f.datums];
                        if (e.target.value) next[k] = { letter: e.target.value, material_condition: f.datums[k]?.material_condition ?? null };
                        else next.splice(k);
                        set({ datums: next.filter(Boolean) });
                      }}>
                      <option value="">—</option>
                      {letters.map((l) => <option key={l}>{l}</option>)}
                    </select>
                  ))}
                  {f.datums.map((r, k) => (
                    // rule 6: a datum feature of size applies at RMB unless a gauge/fixture pin contacts it
                    <select key={`mc${k}`} className={small} value={r.material_condition ?? ""}
                      title={`datum ${r.letter} boundary (datum feature of size only)`}
                      onChange={(e) => set({ datums: replace(f.datums, k, { ...r,
                        material_condition: (e.target.value || null) as DatumReference["material_condition"] }) })}>
                      <option value="">{r.letter} {asme ? "RMB" : "—"}</option>
                      <option value="MMC">{r.letter} Ⓜ {asme ? "MMB" : "MMR"}</option>
                      <option value="LMC">{r.letter} Ⓛ {asme ? "LMB" : "LMR"}</option>
                    </select>
                  ))}
                  {NEEDS_DATUM.includes(f.characteristic) && f.datums.length === 0 &&
                    <span className="text-xs text-amber-700">needs a datum</span>}
                </div>
              )}
            </div>
          );
        })}
        <Add disabled={!targets} onClick={() => setM({ frames: [...m.frames, {
          characteristic: "POSITION", tolerance: 0.1, diameter_zone: true, material_condition: null, datums: [],
          target: { face_id: null, feature_id: null } }] })}>frame</Add>
      </Section>

      <Section title="Dimension tolerances & inspection" count={m.tolerances.length + m.inspection_dimensions.length}>
        {m.tolerances.map((t, i) => {
          const set = (patch: Partial<typeof t>) => setM({ tolerances: replace(m.tolerances, i, { ...t, ...patch }) });
          return (
            <div key={i} className="space-y-1 rounded bg-slate-50 p-1.5">
              <div className="flex items-center gap-1">
                <select className={`${small} min-w-0 flex-1`} value={t.candidate_id}
                  onChange={(e) => set({ candidate_id: e.target.value })}>{dimOptions}</select>
                <Remove onClick={() => setM({ tolerances: m.tolerances.filter((_, k) => k !== i) })} />
              </div>
              <div className="flex items-center gap-1 text-sm">
                <select className={small} value={t.kind} onChange={(e) => set({ kind: e.target.value as typeof t.kind })}>
                  <option value="SYMMETRIC">± symmetric</option>
                  <option value="DEVIATION">+/− deviation</option>
                  <option value="LIMITS">limits</option>
                </select>
                <span>{t.kind === "SYMMETRIC" ? "±" : "upper"}</span>
                <input className={`${small} w-16`} type="number" step="0.001" value={t.upper}
                  onChange={(e) => set({ upper: Number(e.target.value) })} />
                {t.kind !== "SYMMETRIC" && <>
                  <span>lower</span>
                  <input className={`${small} w-16`} type="number" step="0.001" value={t.lower}
                    onChange={(e) => set({ lower: Number(e.target.value) })} />
                </>}
              </div>
            </div>
          );
        })}
        <Add disabled={!targets} onClick={() => setM({ tolerances: [...m.tolerances,
          { candidate_id: "", kind: "SYMMETRIC", upper: 0.1, lower: 0, fit: null }] })}>tolerance</Add>
        <p className="pt-1 text-xs text-slate-600">Inspection dimensions (drawn in an oval):</p>
        <div className="max-h-28 overflow-y-auto">
          {targets?.dimensions.map((d) => (
            <label key={d.id} className="flex items-center gap-1.5 text-xs">
              <input type="checkbox" checked={m.inspection_dimensions.includes(d.id)}
                onChange={(e) => setM({ inspection_dimensions: e.target.checked
                  ? [...m.inspection_dimensions, d.id] : m.inspection_dimensions.filter((x) => x !== d.id) })} />
              {d.text.replace("\n", " ")}
            </label>
          ))}
        </div>
      </Section>

      <Section title="Threads" count={m.threads.length}>
        {m.threads.map((t, i) => (
          <div key={i} className="flex items-center gap-1">
            <select className={`${small} min-w-0 flex-1`} value={t.feature_id}
              onChange={(e) => setM({ threads: replace(m.threads, i, { ...t, feature_id: e.target.value }) })}>
              <option value="">— hole —</option>
              {targets?.features.filter((f) => f.type === "HOLE").map((f) =>
                <option key={f.id} value={f.id}>{featureLabel(f)}</option>)}
            </select>
            <input className={`${small} w-24`} placeholder="M8x1.25-6H" value={t.designation}
              onChange={(e) => setM({ threads: replace(m.threads, i, { ...t, designation: e.target.value }) })} />
            <input className={`${small} w-14`} type="number" placeholder="depth" value={t.depth ?? ""}
              onChange={(e) => setM({ threads: replace(m.threads, i, { ...t, depth: e.target.value ? Number(e.target.value) : null }) })} />
            <Remove onClick={() => setM({ threads: m.threads.filter((_, k) => k !== i) })} />
          </div>
        ))}
        <Add disabled={!targets} onClick={() => setM({ threads: [...m.threads, { feature_id: "", designation: "", depth: null }] })}>
          thread
        </Add>
      </Section>

      <Section title="Surface finish symbols" count={m.surface_finish_marks.length}>
        {m.surface_finish_marks.map((s, i) => (
          <div key={i} className="flex items-center gap-1">
            <select className={`${small} min-w-0 flex-1`} value={targetKey(s.target)}
              onChange={(e) => setM({ surface_finish_marks: replace(m.surface_finish_marks, i, { ...s, target: parseTarget(e.target.value) }) })}>
              {targetOptions(true, false)}
            </select>
            <span className="text-sm">Ra</span>
            <input className={`${small} w-14`} type="number" step="0.1" min="0" value={s.ra_um}
              onChange={(e) => setM({ surface_finish_marks: replace(m.surface_finish_marks, i, { ...s, ra_um: Number(e.target.value) }) })} />
            <Remove onClick={() => setM({ surface_finish_marks: m.surface_finish_marks.filter((_, k) => k !== i) })} />
          </div>
        ))}
        <Add disabled={!targets} onClick={() => setM({ surface_finish_marks: [...m.surface_finish_marks,
          { target: { face_id: null, feature_id: null }, ra_um: 1.6 }] })}>symbol</Add>
      </Section>

      <Section title="Feature notes (leader)" count={m.feature_notes.length}>
        {m.feature_notes.map((n, i) => (
          <div key={i} className="flex items-center gap-1">
            <select className={`${small} w-1/2`} value={targetKey(n.target)}
              onChange={(e) => setM({ feature_notes: replace(m.feature_notes, i, { ...n, target: parseTarget(e.target.value) }) })}>
              {targetOptions()}
            </select>
            <input className={`${small} min-w-0 flex-1`} maxLength={60} placeholder="e.g. BEARING SURFACE" value={n.text}
              onChange={(e) => setM({ feature_notes: replace(m.feature_notes, i, { ...n, text: e.target.value }) })} />
            <Remove onClick={() => setM({ feature_notes: m.feature_notes.filter((_, k) => k !== i) })} />
          </div>
        ))}
        <Add disabled={!targets} onClick={() => setM({ feature_notes: [...m.feature_notes,
          { target: { face_id: null, feature_id: null }, text: "" }] })}>note</Add>
      </Section>

      <Section title="Sheet notes" count={m.notes.length}>
        <p className="text-xs text-slate-500">One note per line; printed as “Note: 1) … 2) …” above the title block.</p>
        <textarea className={`${input} h-20`} value={m.notes.join("\n")} data-testid="sheet-notes"
          onChange={(e) => setM({ notes: e.target.value.split("\n").slice(0, 11) })} />
      </Section>

      <Section title="Revisions" count={m.revisions.length}>
        {m.revisions.map((r, i) => (
          <div key={i} className="grid grid-cols-[40px_1fr_80px_70px_20px] items-center gap-1">
            {(["revision", "description", "date", "approved_by"] as const).map((k) => (
              <input key={k} className={small} placeholder={k.replace("_", " ")} value={r[k]}
                onChange={(e) => setM({ revisions: replace(m.revisions, i, { ...r, [k]: e.target.value }) })} />
            ))}
            <Remove onClick={() => setM({ revisions: m.revisions.filter((_, k) => k !== i) })} />
          </div>
        ))}
        <Add onClick={() => setM({ revisions: [...m.revisions, { revision: "", description: "", date: "", approved_by: "" }] })}>
          revision
        </Add>
      </Section>
    </div>
  );
}

/** Drop incomplete rows (e.g. a datum without a target) before sending. */
export function cleanManufacturing(m: ManufacturingAnnotations): ManufacturingAnnotations {
  const has = (t: { face_id: string | null; feature_id: string | null }) => Boolean(t.face_id || t.feature_id);
  return {
    ...m,
    datums: m.datums.filter((d) => has(d.target)),
    frames: m.frames.filter((f) => has(f.target) && f.tolerance > 0),
    tolerances: m.tolerances.filter((t) => t.candidate_id),
    threads: m.threads.filter((t) => t.feature_id && t.designation.trim().length >= 2),
    surface_finish_marks: m.surface_finish_marks.filter((s) => has(s.target) && s.ra_um > 0),
    feature_notes: m.feature_notes.filter((n) => has(n.target) && n.text.trim()),
    notes: m.notes.map((n) => n.trim()).filter(Boolean),
    revisions: m.revisions.filter((r) => r.revision.trim()),
  };
}
