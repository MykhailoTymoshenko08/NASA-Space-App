import { useQuery } from "@tanstack/react-query";
import { useRef } from "react";
import { api, unwrap, type AnalysisJob, type AnalysisRequest } from "@/shared/api";

/** POST /analyses: starts the async job (202). */
export const createAnalysisJob = (body: AnalysisRequest) => unwrap(api.POST("/analyses", { body }));

export const analysisJobKey = (jobId: string) => ["analysis", jobId] as const;

const isDone = (job: AnalysisJob | undefined) => job?.status === "succeeded" || job?.status === "failed";

/** Poll interval from the contract: every 2 s, back off to 5 s after 30 s. */
export const pollDelayMs = (elapsedMs: number) => (elapsedMs > 30_000 ? 5_000 : 2_000);

/** GET /analyses/{job_id}, polled until the job succeeds or fails. */
export function useAnalysisJob(jobId: string) {
  const startedAt = useRef<{ id: string; at: number }>({ id: jobId, at: Date.now() });
  if (startedAt.current.id !== jobId) startedAt.current = { id: jobId, at: Date.now() };

  return useQuery({
    queryKey: analysisJobKey(jobId),
    queryFn: ({ signal }) => unwrap(api.GET("/analyses/{job_id}", { params: { path: { job_id: jobId } }, signal })),
    refetchInterval: (query) => (isDone(query.state.data) ? false : pollDelayMs(Date.now() - startedAt.current.at)),
    refetchIntervalInBackground: true,
    // A finished job never changes.
    staleTime: (query) => (isDone(query.state.data) ? Infinity : 0),
  });
}
