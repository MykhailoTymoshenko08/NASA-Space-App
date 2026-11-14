import { useParams } from "react-router";
import { PagePlaceholder } from "@/shared/ui/placeholder";

/** Route stub. Polling GET /analyses/{job_id} and the results view come in a later step. */
export function AnalysisPage() {
  const { jobId } = useParams();
  return (
    <PagePlaceholder title="Your analysis">
      <p>We received your request. The results page is coming next.</p>
      {jobId && (
        <p>
          Request number: <code>{jobId}</code>
        </p>
      )}
    </PagePlaceholder>
  );
}
