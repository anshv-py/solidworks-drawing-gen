import { useRef, useState } from "react";

interface Props {
  disabled: boolean;
  onFile: (file: File) => void;
}

const ACCEPT = ".step,.stp,.stl";

export default function UploadPanel({ disabled, onFile }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        const f = e.dataTransfer.files[0];
        if (f && !disabled) onFile(f);
      }}
      className={`rounded-lg border-2 border-dashed p-4 text-center text-sm ${drag ? "border-blue-500 bg-blue-50" : "border-slate-300 bg-white"}`}
    >
      <p className="font-medium">Upload CAD model</p>
      <p className="mt-1 text-slate-500">STEP / STP (exact B-Rep) or STL (tessellated, approximate)</p>
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        className="mt-3 rounded bg-blue-600 px-3 py-1.5 text-white disabled:opacity-50"
      >
        Choose file…
      </button>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="hidden"
        data-testid="file-input"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}
