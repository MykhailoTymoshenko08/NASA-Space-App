import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { buildFieldSearch, FieldFacts, parseFieldSearch, useFieldSnapshot } from "@/entities/field";
import { MetricGridSkeleton } from "@/entities/metric";
import { AnalysisSetupSections, CreateAnalysisPanel, useAnalysisSetup } from "@/features/configure-analysis";
import { CropBudgetInputs, parseCropBudgets, type CropBudgetDraft } from "@/features/configure-budget";
import { ApiError, friendlyMessage } from "@/shared/api";
import { analysisPath, fieldPath, ROUTES } from "@/shared/config";
import { useDocumentTitle } from "@/shared/lib";
import { ButtonLink } from "@/shared/ui/button";
import { ErrorPanel } from "@/shared/ui/feedback";
import { PageColumns, PageIntro, Panel, SectionTitle } from "@/shared/ui/layout";
import { IndeterminateBar } from "@/shared/ui/progress";
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
  const [cropBudgets, setCropBudgets] = useState<CropBudgetDraft[]>([]);
  const cropOverrides = useMemo(() => parseCropBudgets(cropBudgets), [cropBudgets]);

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
        <>
          {/* Same loading look as the Field page: status panel with a sliding bar, then grey tiles. */}
          <Panel gap={14} role="status">
            <SectionTitle>Reading NASA data for this field</SectionTitle>
            <IndeterminateBar />
            <p className={s.muted}>This usually takes under 2 seconds.</p>
          </Panel>
          <MetricGridSkeleton />
        </>
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
      {selection && (
        <>
          <AnalysisSetupSections setup={setup} />
          <Panel>
            <CropBudgetInputs rows={cropBudgets} onChange={setCropBudgets} />
          </Panel>
        </>
      )}
    </>
  );

  const aside = (
    <>
      <CreateAnalysisPanel
        setup={setup}
        disabled={!selection}
        cropOverrides={cropOverrides}
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
      <PageColumns main={main} aside={aside} asideLabel="Create the analysis" stickyAside />
    </div>
  );
}
