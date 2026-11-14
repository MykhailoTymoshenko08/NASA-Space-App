import { useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { buildFieldSearch, FieldFacts, parseFieldSearch, useFieldSnapshot } from "@/entities/field";
import { AnalysisSetupSections, CreateAnalysisPanel, useAnalysisSetup } from "@/features/configure-analysis";
import { ApiError, friendlyMessage } from "@/shared/api";
import { analysisPath, fieldPath, ROUTES } from "@/shared/config";
import { useDocumentTitle } from "@/shared/lib";
import { ButtonLink } from "@/shared/ui/button";
import { ErrorPanel, Skeleton } from "@/shared/ui/feedback";
import { PageColumns, PageIntro, Panel, SectionTitle } from "@/shared/ui/layout";
import { choicesSearch, withParams } from "../lib/choices-url";
import s from "./analysis-page.module.css";

/** /analysis?field_id=.. : priorities, crop history and horizon, then POST /analyses. */
export function AnalysisSetupPage() {
  useDocumentTitle("Set up your analysis");
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const parsed = useMemo(() => parseFieldSearch(params), [params]);
  // Same query as the Field page, so it is usually already cached.
  const snapshot = useFieldSnapshot(parsed.ok ? parsed.request.ref : null);
  const selection = snapshot.data?.selection ?? null;
  const setup = useAnalysisSetup(selection);

  const fieldSearch = parsed.ok
    ? buildFieldSearch({
        fieldId: "field_id" in parsed.request.ref ? parsed.request.ref.field_id : null,
        point: parsed.request.point,
      })
    : "";

  if (!parsed.ok) {
    return (
      <>
        <PageIntro title="Set up your analysis" />
        <PageColumns
          asideLabel="Next step"
          main={
            <ErrorPanel
              title="Pick a field first"
              message="This link doesn't say which field to analyze."
              actions={
                <ButtonLink to={ROUTES.pickField} variant="primary" size="md">
                  Pick a field
                </ButtonLink>
              }
            />
          }
          aside={null}
        />
      </>
    );
  }

  const main = (
    <>
      {snapshot.isPending && (
        <Panel role="status">
          <SectionTitle>Reading this field</SectionTitle>
          <Skeleton height={44} />
          <Skeleton height={44} soft />
        </Panel>
      )}
      {snapshot.isError && (
        <ErrorPanel
          title="We could not load this field"
          message={friendlyMessage(snapshot.error)}
          code={snapshot.error instanceof ApiError ? snapshot.error.code : null}
          actions={
            <ButtonLink to={ROUTES.pickField} variant="secondary" size="md">
              Pick another field
            </ButtonLink>
          }
        />
      )}
      {selection && <AnalysisSetupSections setup={setup} />}
    </>
  );

  const aside = (
    <>
      <CreateAnalysisPanel
        setup={setup}
        disabled={!selection}
        onCreated={(jobId) =>
          navigate(analysisPath(jobId, withParams(fieldSearch, choicesSearch(setup.priorities, setup.horizon))))
        }
      />
      {selection && <FieldFacts selection={selection} tone="wash" showNote={false} showCrop={false} />}
    </>
  );

  return (
    <div className={s.page}>
      <PageIntro
        back={{ to: fieldPath(fieldSearch), label: "Back to base conditions" }}
        title="Set up your analysis"
        lead="Optional. Leave everything as it is for a balanced analysis."
      />
      <PageColumns main={main} aside={aside} asideLabel="Create the analysis" />
    </div>
  );
}
