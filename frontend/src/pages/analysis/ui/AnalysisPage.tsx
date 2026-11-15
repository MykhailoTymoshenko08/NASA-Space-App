import { useMemo } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useAnalysisJob } from "@/entities/analysis";
import { buildFieldSearch, FieldFacts, parseFieldSearch, selectionSearch } from "@/entities/field";
import { ExportPdfButton } from "@/features/export-pdf";
import { SaveFieldButton } from "@/features/save-field";
import { ApiError, friendlyMessage } from "@/shared/api";
import { analysisSetupPath, fieldPath, ROUTES } from "@/shared/config";
import { useDocumentTitle } from "@/shared/lib";
import { ButtonLink } from "@/shared/ui/button";
import { ErrorPanel } from "@/shared/ui/feedback";
import { PageColumns, PageIntro, Panel } from "@/shared/ui/layout";
import { ProgressBar } from "@/shared/ui/progress";
import { AnalysisResultView } from "@/widgets/analysis-result";
import { readChoices } from "../lib/choices-url";
import s from "./analysis-page.module.css";

const COPY = {
  running: { title: "Creating your analysis", lead: "Hold on while we put it together." },
  result: { title: "Your analysis", lead: "Crop rotation strategies for this field, ranked by how well they fit." },
  failed: { title: "Your analysis", lead: "Something went wrong." },
} as const;

/** /analysis/:jobId : polls GET /analyses/{job_id} (2 s, then 5 s after 30 s) and shows running, result or failed. */
export function AnalysisPage() {
  const { jobId = "" } = useParams();
  const [params] = useSearchParams();
  const job = useAnalysisJob(jobId);
  const choices = useMemo(() => readChoices(params), [params]);
  const parsed = useMemo(() => parseFieldSearch(params), [params]);
  const result = job.data?.status === "succeeded" ? (job.data.result ?? null) : null;

  // Where "Try again" and "Back" go: the result's own field when known, else the field in the URL.
  const fieldSearch = result
    ? selectionSearch(result.selection)
    : parsed.ok
      ? buildFieldSearch({
          fieldId: "field_id" in parsed.request.ref ? parsed.request.ref.field_id : null,
          point: parsed.request.point,
        })
      : "";

  const phase: keyof typeof COPY =
    job.isError || job.data?.status === "failed" || (job.data?.status === "succeeded" && !result)
      ? "failed"
      : result
        ? "result"
        : "running";
  useDocumentTitle(COPY[phase].title);

  const tryAgain = fieldSearch ? analysisSetupPath(fieldSearch) : ROUTES.pickField;

  let main;
  if (phase === "running") {
    main = (
      <Panel gap={16} role="status" className={s.running}>
        <h2 className={s.h2}>Creating your analysis</h2>
        <ProgressBar percent={job.data?.progress.percent ?? 0} label="Analysis progress" />
        <p className={s.muted}>{job.data?.progress.stage ?? "Queued"}</p>
        <p className={s.small}>You can stay on this page. It usually takes under a minute.</p>
      </Panel>
    );
  } else if (phase === "failed") {
    const err = job.data?.error;
    main = (
      <ErrorPanel
        title="We could not finish your analysis"
        message={err ? `${err.message} Nothing is saved from this run.` : friendlyMessage(job.error)}
        code={err?.code ?? (job.error instanceof ApiError ? job.error.code : null)}
        requestId={err?.request_id ?? (job.error instanceof ApiError ? job.error.requestId : null)}
        actions={
          <>
            <ButtonLink to={tryAgain} variant="primary" size="md">
              Try again
            </ButtonLink>
            {fieldSearch && (
              <ButtonLink to={fieldPath(fieldSearch)} variant="secondary" size="md">
                Back to base conditions
              </ButtonLink>
            )}
          </>
        }
      />
    );
  } else {
    main = <AnalysisResultView result={result!} priorities={choices.priorities} horizon={choices.horizon} />;
  }

  const aside = (
    <>
      {result && (
        <Panel className={s.noPrint}>
          <ExportPdfButton />
          <SaveFieldButton selection={result.selection} showMyFieldsLink />
          <ButtonLink to={tryAgain} variant="ghost" className={s.rerun}>
            Change priorities and run again
          </ButtonLink>
          <Link to={ROUTES.pickField} className={s.another}>
            Analyze another field
          </Link>
        </Panel>
      )}
      {result && <FieldFacts selection={result.selection} tone="wash" showNote={false} showCrop={false} />}
    </>
  );

  return (
    <div className={s.page}>
      <PageIntro
        back={fieldSearch ? { to: fieldPath(fieldSearch), label: "Back to base conditions" } : undefined}
        title={COPY[phase].title}
        lead={COPY[phase].lead}
      />
      {/* Export PDF panel starts level with the Best fit card, not with the section heading. */}
      <PageColumns main={main} aside={aside} asideLabel="Actions" alignAsideTo="[data-best-fit-anchor]" stickyAside />
    </div>
  );
}
