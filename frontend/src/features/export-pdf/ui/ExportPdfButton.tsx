import { useMutation } from "@tanstack/react-query";
import { fetchAnalysisReport } from "@/entities/analysis";
import { friendlyMessage } from "@/shared/api";
import { saveFile } from "@/shared/lib";
import { Button } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { IndeterminateBar } from "@/shared/ui/progress";

/**
 * Export to PDF is the only export (no zip, no per-dataset downloads).
 * GET /analyses/{job_id}/report.pdf: the backend renders the finished analysis as an A4 report
 * (summary, strategy cards, conditions, data used) and the browser downloads it.
 */
export function ExportPdfButton({ jobId }: { jobId: string }) {
  const report = useMutation({
    mutationFn: () => fetchAnalysisReport(jobId),
    onSuccess: ({ blob, filename }) => saveFile(blob, filename),
  });
  const loading = report.isPending;

  return (
    <>
      <Button
        variant="primary"
        size="lg"
        block
        onClick={() => report.mutate()}
        disabled={loading}
        aria-describedby={loading || report.isSuccess || report.isError ? `${jobId}-pdf-status` : undefined}
      >
        <Icon name={loading ? "download" : "file"} />
        {loading ? "Preparing your PDF..." : report.isError ? "Try the PDF again" : "Export to PDF"}
      </Button>
      {loading && (
        <div id={`${jobId}-pdf-status`} role="status">
          <IndeterminateBar />
          <span className="visually-hidden">Making your PDF report. This takes a few seconds.</span>
        </div>
      )}
      {report.isSuccess && (
        <Message tone="success" role="status" id={`${jobId}-pdf-status`}>
          Your PDF report is downloaded. Look in your Downloads folder.
        </Message>
      )}
      {report.isError && (
        <Message tone="error" role="alert" id={`${jobId}-pdf-status`}>
          {friendlyMessage(report.error)}
        </Message>
      )}
    </>
  );
}
