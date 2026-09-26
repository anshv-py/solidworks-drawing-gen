import { useRef, useState } from "react";

interface Props {
  disabled: boolean;
  onFile: (file: File) => void;
  /** set when a model is loaded: upload the next CAD version of the same part */
  onNewVersion?: (file: File) => void;
}

const ACCEPT = ".step,.stp,.stl";

export default function UploadPanel({ disabled, onFile, onNewVersion }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const version = useRef<HTMLInputElement>(null);
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
      {onNewVersion && (
        <>
          <button type="button" disabled={disabled} onClick={() => version.current?.click()}
            title="the drawing is regenerated for it with your settings, and a revision is logged"
            className="ml-2 mt-3 rounded border border-blue-600 px-3 py-1.5 text-blue-700 disabled:opacity-50">
            Upload new version…
          </button>
          <input ref={version} type="file" accept={ACCEPT} className="hidden" data-testid="version-input"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onNewVersion(f);
              e.target.value = "";
            }} />
        </>
      )}
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
