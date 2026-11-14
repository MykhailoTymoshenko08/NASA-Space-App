import { useMemo } from "react";
import { useSearchParams } from "react-router";
import {
  buildFieldSearch,
  fieldSizeM,
  FieldOverview,
  parseFieldSearch,
  placeLine,
  selectionSearch,
  useFieldSnapshot,
} from "@/entities/field";
import { Glossary, MetricGridSkeleton, MetricGroups, SourcesList, SourcesStrip, useSourceRegistry } from "@/entities/metric";
import { SaveFieldButton } from "@/features/save-field";
import { ApiError, friendlyMessage, type Snapshot } from "@/shared/api";
import { analysisSetupPath, ROUTES } from "@/shared/config";
import { useDocumentTitle } from "@/shared/lib";
import { Button, ButtonLink } from "@/shared/ui/button";
import { ErrorPanel, Message } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { Container, PageColumns, PageIntro, Panel, SectionTitle } from "@/shared/ui/layout";
import { IndeterminateBar } from "@/shared/ui/progress";
import s from "./field-page.module.css";

/**
 * /field?field_id=.. (or ?lat=..&lon=..). One POST /snapshots returns the resolved field and its metrics,
 * grouped by category. Every value shows its quality, source and pixel size.
 */
export function FieldPage() {
  useDocumentTitle("Base conditions");
  const [params] = useSearchParams();
  const parsed = useMemo(() => parseFieldSearch(params), [params]);
  const query = useFieldSnapshot(parsed.ok ? parsed.request.ref : null);

  if (!parsed.ok) return <MissingLocation problem={parsed.problem} />;

  const snapshot = query.data;
  const selection = snapshot?.selection ?? null;
  // Before the snapshot loads, the URL already identifies the field for "Get analysis".
  const search = selection
    ? selectionSearch(selection)
    : buildFieldSearch({
        fieldId: "field_id" in parsed.request.ref ? parsed.request.ref.field_id : null,
        point: parsed.request.point,
      });

  const main = (
    <>
      {query.isPending && (
        <>
          <Panel gap={14} role="status">
            <SectionTitle>Reading NASA data for this field</SectionTitle>
            <IndeterminateBar />
            <p className={s.muted}>This usually takes under 2 seconds.</p>
          </Panel>
          <MetricGridSkeleton />
        </>
      )}

      {query.isError && (
        <ErrorPanel
          title="We could not get conditions for this point"
          message={friendlyMessage(query.error)}
          code={query.error instanceof ApiError ? query.error.code : null}
          requestId={query.error instanceof ApiError ? query.error.requestId : null}
          actions={
            <>
              <Button variant="primary" size="md" onClick={() => void query.refetch()} disabled={query.isFetching}>
                {query.isFetching ? "Trying again…" : "Try again"}
              </Button>
              <ButtonLink to={ROUTES.pickField} variant="secondary" size="md">
                Pick another field
              </ButtonLink>
            </>
          }
        />
      )}

      {snapshot && <FieldConditions snapshot={snapshot} />}
    </>
  );

  const aside = (
    <Panel gap={14}>
      <SectionTitle>Want the full picture?</SectionTitle>
      <p className={s.muted}>Get an analysis that compares crop rotations for this field and shows why each one fits or not.</p>
      <ButtonLink to={analysisSetupPath(search)} variant="primary" size="lg" block>
        Get analysis
        <Icon name="arrow-right" />
      </ButtonLink>
      {selection && <SaveFieldButton selection={selection} />}
      <p className={s.fine}>
        Each value says if it was measured, modeled or estimated. The nitrogen figure is an estimate, not a soil lab test.
      </p>
    </Panel>
  );

  return (
    <>
      <PageIntro
        back={{ to: ROUTES.pickField, label: "Back to pick a field" }}
        title="Base conditions"
        lead={selection ? placeLine(selection) : "Estimated field area."}
      />
      <div aria-live="polite" className="visually-hidden">
        {query.isPending ? "Loading base conditions." : query.isError ? "Base conditions could not be loaded." : "Base conditions loaded."}
      </div>
      <PageColumns main={main} aside={aside} asideLabel="Next step" />
    </>
  );
}

/** Loaded state: the field, the source strip, metric groups, then the full Sources list and Glossary. */
function FieldConditions({ snapshot }: { snapshot: Snapshot }) {
  const registry = useSourceRegistry(snapshot.metrics);
  return (
    <>
      <FieldOverview selection={snapshot.selection} />
      <SourcesStrip registry={registry} />
      <MetricGroups metrics={snapshot.metrics} fieldSizeM={fieldSizeM(snapshot.selection.area_ha)} registry={registry} />
      <p className={s.fine}>Values from the API are metric and shown here in US units.</p>
      <SourcesList registry={registry} />
      <Glossary />
    </>
  );
}

function MissingLocation({ problem }: { problem: "missing" | "invalid" }) {
  return (
    <>
      <PageIntro title="Pick a field first" />
      <Container>
        <div className={s.missing}>
        <Message tone="error" role="alert">
          {problem === "missing"
            ? "This link doesn't say which field to show."
            : "The location in this link isn't valid. Latitude must be between -90 and 90, longitude between -180 and 180."}
        </Message>
        <ButtonLink to={ROUTES.pickField} variant="primary" size="lg">
          Pick your field
          <Icon name="arrow-right" />
        </ButtonLink>
        </div>
      </Container>
    </>
  );
}
