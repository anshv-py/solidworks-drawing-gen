import type { GeometryIR } from "../generated/geometry-ir";
import { countByType, mm } from "../lib/features";

export default function GeometrySummary({ ir }: { ir: GeometryIR }) {
  const [x, y, z] = ir.bounding_box.size;
  const mp = ir.mass_properties;
  const exact = ir.representation === "EXACT_BREP";
  const counts = countByType(ir);
  const meta = ir.cad_metadata;
  return (
    <div className="rounded-lg bg-white p-3 text-sm shadow-sm" data-testid="geometry-summary">
      <div className="flex items-center justify-between">
        <span className="font-medium">{ir.source.filename}</span>
        <span className={`rounded px-2 py-0.5 text-xs ${exact ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>
          {exact ? "Exact B-Rep (STEP)" : "Tessellated (STL) – approximate"}
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
        <dt className="text-slate-500">Size (mm)</dt>
        <dd data-testid="bbox">{mm(x)} × {mm(y)} × {mm(z)}</dd>
        <dt className="text-slate-500">Volume</dt>
        <dd>{mp.volume != null ? `${mm(mp.volume, 1)} mm³` : "n/a (not closed)"}</dd>
        <dt className="text-slate-500">Surface area</dt>
        <dd>{mm(mp.surface_area, 1)} mm²</dd>
        <dt className="text-slate-500">Topology</dt>
        <dd>
          {ir.topology.solids} solid · {ir.topology.faces} faces · {ir.topology.edges} edges
          {ir.topology.triangles != null && ` · ${ir.topology.triangles} triangles`}
        </dd>
        <dt className="text-slate-500">File units</dt>
        <dd>{ir.source.file_length_units.join(", ") || "none declared (assumed mm)"}</dd>
        <dt className="text-slate-500">Features</dt>
        <dd>{Object.entries(counts).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(", ") || "none recognized"}</dd>
        <dt className="text-slate-500">From the CAD file</dt>
        <dd data-testid="cad-metadata">
          {[["name", meta?.name], ["part no.", meta?.part_number], ["rev.", meta?.revision],
            ["material", meta?.material], ["mass", meta?.mass_g != null ? `${meta.mass_g} g` : null]]
            .filter(([, v]) => v)
            .map(([k, v]) => `${k} ${v}`)
            .join(" · ") || "no product data (title-block fields stay empty until entered)"}
        </dd>
      </dl>
      {ir.diagnostics.length > 0 && (
        <ul className="mt-2 space-y-1">
          {ir.diagnostics.map((d) => (
            <li key={d.code} className={`rounded px-2 py-1 text-xs ${d.severity === "INFO" ? "bg-slate-100" : "bg-amber-50 text-amber-900"}`}>
              <span className="font-mono">{d.code}</span> – {d.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
