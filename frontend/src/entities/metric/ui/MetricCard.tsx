import type { CSSProperties } from "react";
import { Button } from "@/shared/ui/button";
import { Badge, Message, Skeleton } from "@/shared/ui/feedback";
import { MonoLabel } from "@/shared/ui/layout";
import type { PresentedMetric } from "../lib/present";
import s from "./metric-card.module.css";

export type MetricCardState =
  | { kind: "loading" }
  | { kind: "error"; message: string; onRetry: () => void; retrying: boolean }
  | { kind: "ready"; metric: PresentedMetric; onRetry: () => void; retrying: boolean };

type Props = { title: string; accent?: string; state: MetricCardState };

/** One measure: label + source, a big number with its unit, and its own loading and error states. */
export function MetricCard({ title, accent, state }: Props) {
  const style = accent ? ({ "--accent": accent } as CSSProperties) : undefined;
  const source = state.kind === "ready" ? state.metric.sourceName : null;

  return (
    <article className={s.card} style={style} aria-busy={state.kind === "loading"}>
      <header className={s.head}>
        <MonoLabel as="h3" className={s.label}>
          {accent && <span className={s.swatch} aria-hidden="true" />}
          {title}
        </MonoLabel>
        {source && <span className={s.source}>{source}</span>}
      </header>

      {state.kind === "loading" && (
        <>
          <Skeleton width="55%" height={48} />
          <Skeleton height={40} soft />
          <p className={s.muted}>Fetching from our server…</p>
        </>
      )}

      {state.kind === "error" && (
        <ErrorBody message={state.message} onRetry={state.onRetry} retrying={state.retrying} />
      )}

      {state.kind === "ready" && state.metric.status === "unavailable" && (
        <ErrorBody
          message={`${state.metric.sourceName} did not answer. Your other values are fine.`}
          detail={state.metric.reason}
          onRetry={state.onRetry}
          retrying={state.retrying}
        />
      )}

      {state.kind === "ready" && state.metric.status === "ok" && (
        <>
          <div className={s.valueRow}>
            <span className={s.value}>{state.metric.value}</span>
            {state.metric.unit && <span className={s.unit}>{state.metric.unit}</span>}
            {state.metric.badge && (
              <span className={s.badge}>
                <Badge tone={state.metric.badge.tone}>{state.metric.badge.text}</Badge>
              </span>
            )}
          </div>
          {state.metric.when && <p className={s.when}>{state.metric.when}</p>}
          {state.metric.coarseWarning && <p className={s.warning}>{state.metric.coarseWarning}</p>}
          {state.metric.note && <p className={s.note}>{state.metric.note}</p>}
        </>
      )}
    </article>
  );
}

function ErrorBody({
  message,
  detail,
  onRetry,
  retrying,
}: {
  message: string;
  detail?: string;
  onRetry: () => void;
  retrying: boolean;
}) {
  return (
    <>
      <Message tone="error">
        <span>{message}</span>
        {detail && <span className={s.detail}>{detail}</span>}
      </Message>
      <Button variant="secondary" onClick={onRetry} disabled={retrying}>
        {retrying ? "Trying again…" : "Try again"}
      </Button>
    </>
  );
}
