import type { UseQueryResult } from "@tanstack/react-query";
import { FEATURED_METRICS, MetricCard, SourcesList, presentMetric, type MetricCardState } from "@/entities/metric";
import { ApiError, friendlyMessage, type Metric, type Snapshot } from "@/shared/api";
import { ROUTES } from "@/shared/config";
import { ButtonLink } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import s from "./base-conditions.module.css";

const FEATURED_KEYS = new Set(FEATURED_METRICS.map((f) => f.key));
const PICK_AGAIN_CODES = new Set(["OUTSIDE_COVERAGE", "NOT_FOUND", "VALIDATION_ERROR"]);

const updatedFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

/** The four design cards, any extra metrics from the backend, and the sources list. */
export function BaseConditions({ query }: { query: UseQueryResult<Snapshot> }) {
  const { data, error, isPending, isError, isFetching, refetch } = query;
  const retry = () => void refetch();
  const areaHa = data?.selection.area_ha ?? null;

  const cardState = (metric: Metric | undefined): MetricCardState => {
    if (isPending) return { kind: "loading" };
    if (isError || !data) return { kind: "error", message: friendlyMessage(error), onRetry: retry, retrying: isFetching };
    const presented = metric
      ? presentMetric(metric, areaHa)
      : ({ status: "unavailable", sourceName: "Our server", reason: "This value was not included in the answer." } as const);
    return { kind: "ready", metric: presented, onRetry: retry, retrying: isFetching };
  };

  const extras = data?.metrics.filter((m) => !FEATURED_KEYS.has(m.key)) ?? [];

  return (
    <section className={s.wrap} aria-labelledby="base-title">
      <div className={s.head}>
        <h2 id="base-title" className={s.title}>
          Base conditions
        </h2>
        {data && <span className={s.meta}>Updated {updatedFmt.format(new Date(data.generated_at))}</span>}
      </div>

      <div aria-live="polite" className="visually-hidden">
        {isPending ? "Loading base conditions." : isError ? "Base conditions could not be loaded." : "Base conditions loaded."}
      </div>

      {isError && (
        <Message tone="error" role="alert">
          <span>{friendlyMessage(error)}</span>
          {error instanceof ApiError && error.requestId && (
            <span className={s.requestId}>Request ID: {error.requestId}</span>
          )}
          {error instanceof ApiError && PICK_AGAIN_CODES.has(error.code) && (
            <ButtonLink to={ROUTES.pickField} variant="link">
              Choose a different field
            </ButtonLink>
          )}
        </Message>
      )}

      <div className={s.grid}>
        {FEATURED_METRICS.map((f) => (
          <MetricCard
            key={f.key}
            title={f.title}
            accent={f.accent}
            state={cardState(data?.metrics.find((m) => m.key === f.key))}
          />
        ))}
      </div>

      {extras.length > 0 && (
        <>
          <h3 className={s.subTitle}>More from this spot</h3>
          <div className={s.grid}>
            {extras.map((m) => (
              <MetricCard key={m.key} title={m.label} state={cardState(m)} />
            ))}
          </div>
        </>
      )}

      <SourcesList state={isPending ? "loading" : isError || !data ? "error" : { metrics: data.metrics }} />
    </section>
  );
}
