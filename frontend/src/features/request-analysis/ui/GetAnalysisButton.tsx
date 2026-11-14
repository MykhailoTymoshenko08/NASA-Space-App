import { useNavigate } from "react-router";
import { ApiError, friendlyMessage, type SelectionRef } from "@/shared/api";
import { analysisPath } from "@/shared/config";
import { Button } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { useCreateAnalysis } from "../api/create-analysis";
import s from "./get-analysis.module.css";

type Props = {
  /** The field to analyse, or null while it is still loading. */
  selection: SelectionRef | null;
  /** Shown under the button while it is disabled, so the user knows why. */
  disabledReason?: string;
};

export function GetAnalysisButton({ selection, disabledReason }: Props) {
  const navigate = useNavigate();
  const create = useCreateAnalysis();
  const disabled = selection === null || create.isPending;

  const onClick = () => {
    if (!selection) return;
    create.mutate(selection, { onSuccess: (job) => navigate(analysisPath(job.job_id)) });
  };

  return (
    <div className={s.wrap}>
      <Button variant="primary" size="lg" block onClick={onClick} disabled={disabled} aria-describedby="analysis-why">
        {create.isPending ? "Requesting…" : "Get analysis"}
        {!create.isPending && <Icon name="arrow-right" />}
      </Button>
      {selection === null && disabledReason && (
        <p id="analysis-why" className={s.why}>
          {disabledReason}
        </p>
      )}
      {create.isError && (
        <Message tone="error" role="alert">
          <span>{friendlyMessage(create.error)}</span>
          {create.error instanceof ApiError && create.error.requestId && (
            <span className={s.requestId}>Request ID: {create.error.requestId}</span>
          )}
        </Message>
      )}
    </div>
  );
}
