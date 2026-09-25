import { useEffect, useState } from "react";
import { TERMINAL, api, isGone, type JobOut } from "./lib/api";

/** Poll a job until it reaches a terminal state. */
export function useJob(jobId: string | null, intervalMs = 400): JobOut | null {
  const [job, setJob] = useState<JobOut | null>(null);
  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const j = await api.job(jobId);
        if (cancelled) return;
        setJob(j);
        if (!TERMINAL.includes(j.state)) timer = setTimeout(tick, intervalMs);
      } catch (e) {
        if (cancelled) return;
        if (isGone(e)) {
          // the server restarted and lost the job: stop polling and say so
          setJob((prev) => ({
            ...(prev ?? { id: jobId, kind: "DRAWING", model_id: "", progress: 0, message: null, created_at: "",
              started_at: null, finished_at: null }),
            state: "FAILED",
            error: { code: "JOB_LOST", message: "The server restarted and lost this job - please run it again." },
          }));
          return;
        }
        timer = setTimeout(tick, intervalMs * 4);
      }
    };
    void tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, intervalMs]);
  return job;
}
