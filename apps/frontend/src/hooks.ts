import { useEffect, useState } from "react";
import { TERMINAL, api, type JobOut } from "./lib/api";

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
      } catch {
        if (!cancelled) timer = setTimeout(tick, intervalMs * 4);
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
