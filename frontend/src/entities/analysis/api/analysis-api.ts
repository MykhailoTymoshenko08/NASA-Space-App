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
export function useAnalysisJob(jobId: string, viewer = "guest", enabled = true) {
  const startedAt = useRef<{ id: string; at: number }>({ id: jobId, at: Date.now() });
  if (startedAt.current.id !== jobId) startedAt.current = { id: jobId, at: Date.now() };

  return useQuery({
    queryKey: [...analysisJobKey(jobId), viewer],
    queryFn: ({ signal }) => unwrap(api.GET("/analyses/{job_id}", { params: { path: { job_id: jobId } }, signal })),
    refetchInterval: (query) => (isDone(query.state.data) ? false : pollDelayMs(Date.now() - startedAt.current.at)),
    refetchIntervalInBackground: true,
    enabled,
    // A finished job never changes.
    staleTime: (query) => (isDone(query.state.data) ? Infinity : 0),
  });
}

export type AnalysisReport = { blob: Blob; filename: string };

/** `attachment; filename="x.pdf"` -> `x.pdf`, or null. */
export function attachmentName(disposition: string | null): string | null {
  const m = disposition?.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  const raw = m?.[1];
  if (!raw) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

/** GET /analyses/{job_id}/report.pdf: the finished analysis as a PDF the backend renders (A4). */
export async function fetchAnalysisReport(jobId: string, signal?: AbortSignal): Promise<AnalysisReport> {
  const call = api.GET("/analyses/{job_id}/report.pdf", {
    params: { path: { job_id: jobId } },
    parseAs: "blob",
    signal,
  });
  const blob = (await unwrap(call)) as Blob;
  const { response } = await call;
  const filename = attachmentName(response.headers.get("Content-Disposition"));
  return { blob, filename: filename ?? `seloai-analysis-${jobId.slice(0, 8)}.pdf` };
}
