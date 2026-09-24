import type { GeometryIR } from "../generated/geometry-ir";
import { describeFeature } from "../lib/features";

interface Props {
  ir: GeometryIR;
  selected: string | null;
  onSelect: (id: string | null) => void;
}

export default function FeatureTable({ ir, selected, onSelect }: Props) {
  if (ir.features.length === 0) {
    return (
      <p className="rounded-lg bg-white p-3 text-sm text-slate-500 shadow-sm">
        No features recognized{ir.representation === "TESSELLATED" ? " (mesh feature recognition is not implemented yet)" : ""}.
      </p>
    );
  }
  return (
    <div className="overflow-hidden rounded-lg bg-white shadow-sm">
      <table className="w-full text-left text-sm" data-testid="feature-table">
        <thead className="bg-slate-50 text-xs uppercase text-slate-500">
          <tr>
            <th className="px-3 py-2">Feature</th>
            <th className="px-3 py-2">Geometry (from OCCT)</th>
            <th className="px-3 py-2 text-right">Conf.</th>
          </tr>
        </thead>
        <tbody>
          {ir.features.map((f) => (
            <tr
              key={f.id}
              onClick={() => onSelect(selected === f.id ? null : f.id)}
              className={`cursor-pointer border-t border-slate-100 ${selected === f.id ? "bg-orange-50" : "hover:bg-slate-50"}`}
              title={`${f.id} · ${f.provenance.method}${f.notes.length ? " · " + f.notes.join("; ") : ""}`}
            >
              <td className="px-3 py-1.5 font-medium">{f.type}</td>
              <td className="px-3 py-1.5 font-mono text-xs">{describeFeature(f)}</td>
              <td className="px-3 py-1.5 text-right">{f.confidence.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
