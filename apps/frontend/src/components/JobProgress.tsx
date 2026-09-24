import type { JobOut } from "../lib/api";

export default function JobProgress({ job }: { job: JobOut }) {
  const failed = job.state === "FAILED";
  return (
    <div className="rounded-lg bg-white p-3 text-sm shadow-sm" data-testid="job-progress">
      <div className="flex justify-between">
        <span className="font-medium">{job.kind === "ANALYZE" ? "Geometry analysis" : "Drawing job"}</span>
        <span className={failed ? "text-red-600" : "text-slate-600"}>{job.state}</span>
      </div>
      <div className="mt-2 h-2 rounded bg-slate-200">
        <div
          className={`h-2 rounded ${failed ? "bg-red-500" : "bg-blue-600"}`}
          style={{ width: `${Math.max(2, job.progress)}%` }}
        />
      </div>
      <p className="mt-1 text-slate-500">{failed ? `${job.error?.code}: ${job.error?.message}` : job.message}</p>
    </div>
  );
}
