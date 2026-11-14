import { useEffect, useMemo } from "react";
import { useSearchParams } from "react-router";
import { areaLine, countyLine, fieldTitle, FieldSketch, parseFieldSearch, useFieldSnapshot } from "@/entities/field";
import { GetAnalysisButton } from "@/features/request-analysis";
import type { SelectionRef } from "@/shared/api";
import { APP_NAME, ROUTES } from "@/shared/config";
import { formatLatLon } from "@/shared/lib";
import { ButtonLink } from "@/shared/ui/button";
import { Message, Skeleton } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { Card, Container } from "@/shared/ui/layout";
import { BaseConditions } from "@/widgets/base-conditions";
import s from "./field-page.module.css";

/**
 * /field?lat=..&lon=.. (or ?field_id=..). Reads the location from the URL, asks our backend
 * for a snapshot (POST /snapshots), and shows the field with its base conditions.
 */
export function FieldPage() {
  const [params] = useSearchParams();
  const parsed = useMemo(() => parseFieldSearch(params), [params]);
  const query = useFieldSnapshot(parsed.ok ? parsed.request.ref : null);
  const selection = query.data?.selection ?? null;

  const title = selection
    ? fieldTitle(selection)
    : parsed.ok && "field_id" in parsed.request.ref
      ? `Field ${parsed.request.ref.field_id}`
      : "Your field";

  useEffect(() => {
    document.title = `${title} · ${APP_NAME}`;
  }, [title]);

  if (!parsed.ok) return <MissingLocation problem={parsed.problem} />;

  const point = selection?.anchor ?? parsed.request.point;
  const area = selection ? areaLine(selection) : null;
  // Analyse the backend-resolved field: its id when it has one, otherwise its anchor point.
  const analysisRef: SelectionRef | null = selection
    ? selection.field_id
      ? { field_id: selection.field_id }
      : { point: selection.anchor }
    : null;

  return (
    <>
      <Container as="section" className={s.intro} aria-labelledby="field-title">
        <ButtonLink to={ROUTES.pickField} variant="link" className={s.back}>
          <Icon name="arrow-left" size={18} />
          Choose a different field
        </ButtonLink>
        <h1 id="field-title" className={s.title}>
          {title}
        </h1>
        <p className={s.meta}>
          {selection ? <span>{countyLine(selection)}</span> : query.isPending && <Skeleton width={160} height={20} />}
          {area && <span>{area}</span>}
          {point && <span className={s.coords}>{formatLatLon(point)}</span>}
        </p>
      </Container>

      <Container as="div" className={s.columns}>
        <div className={s.main}>
          <BaseConditions query={query} />
        </div>

        <aside className={s.aside} aria-label="Field outline and next step">
          {!query.isError && <FieldSketch selection={selection} />}
          <Card compact className={s.cta}>
            <h2 className={s.ctaTitle}>Want the full picture?</h2>
            <p className={s.muted}>
              Request an analysis and we send you a package of datasets our data science team selected for this field.
            </p>
            <GetAnalysisButton
              selection={analysisRef}
              disabledReason={
                query.isError ? "Available once this field's base conditions load." : "Available once the field has loaded."
              }
            />
            <p className={s.small}>The nitrogen index is an estimate. It is not a soil lab test.</p>
          </Card>
        </aside>
      </Container>
    </>
  );
}

function MissingLocation({ problem }: { problem: "missing" | "invalid" }) {
  return (
    <Container as="section" className={s.intro} aria-labelledby="field-title">
      <h1 id="field-title" className={s.title}>
        Pick a field first
      </h1>
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
  );
}
