import type { Metric } from "@/shared/api";
import { Badge, Skeleton } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { SectionTitle } from "@/shared/ui/layout";
import { groupMetrics, presentMetric } from "../lib/present";
import s from "./metric-card.module.css";

/** One measure: label + quality pill, the value with its unit, date, source, pixel size and notes. */
export function MetricCard({ metric, fieldSizeM }: { metric: Metric; fieldSizeM: number | null }) {
  const m = presentMetric(metric, fieldSizeM);
  return (
    <article className={s.card} aria-labelledby={`metric-${m.key}`}>
      <div className={s.head}>
        <h3 id={`metric-${m.key}`} className={s.label}>
          {m.label}
        </h3>
        <Badge tone={m.quality.tone}>{m.quality.label}</Badge>
      </div>
      <div className={s.valueRow}>
        <span className={m.available ? s.value : s.valueMissing}>{m.value}</span>
        {m.unit && <span className={s.unit}>{m.unit}</span>}
      </div>
      <div className={s.meta}>{m.when}</div>
      <div className={s.meta}>{m.source}</div>
      {m.pixel && <div className={s.meta}>{m.pixel}</div>}
      {m.coarse && (
        <div className={s.coarse}>
          <Icon name="warning" size={16} />
          <span>Wider than this field. One reading covers many fields around it.</span>
        </div>
      )}
      {m.note && <div className={s.note}>{m.note}</div>}
    </article>
  );
}

/** Metrics in category sections ("Moisture", "Air", ...), as on the Field and Analysis pages. */
export function MetricGroups({
  metrics,
  fieldSizeM,
  headingLevel = 2,
}: {
  metrics: readonly Metric[];
  fieldSizeM: number | null;
  headingLevel?: 2 | 3;
}) {
  return (
    <>
      {groupMetrics(metrics).map((g) => (
        <section key={g.category} className={s.group} aria-label={g.title}>
          <SectionTitle as={headingLevel === 2 ? "h2" : "h3"}>{g.title}</SectionTitle>
          <div className={s.grid}>
            {g.metrics.map((m) => (
              <MetricCard key={m.key} metric={m} fieldSizeM={fieldSizeM} />
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

/** Six grey blocks while metrics load. */
export function MetricGridSkeleton() {
  return (
    <div className={s.grid} aria-hidden="true">
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} height={150} />
      ))}
    </div>
  );
}
