import { useState } from "react";
import { DatasetList, priorityText, sortStrategies, StrategyCard, TimeSeriesChart, yearsText } from "@/entities/analysis";
import { fieldSizeM } from "@/entities/field";
import { MetricGroups } from "@/entities/metric";
import type { AnalysisResult, Priority } from "@/shared/api";
import { formatDateTime } from "@/shared/lib";
import { Note } from "@/shared/ui/feedback";
import s from "./analysis-result.module.css";

type Props = {
  result: AnalysisResult;
  /** Choices the farmer made, if known (from the setup screen). */
  priorities: readonly Priority[] | null;
  horizon: number | null;
};

/** The result: caveats, ranked strategies, history charts, current conditions, datasets and the disclaimer. */
export function AnalysisResultView({ result, priorities, horizon }: Props) {
  const strategies = sortStrategies(result.strategies);
  const baseline = strategies.find((st) => st.is_current)?.score ?? null;
  const [open, setOpen] = useState<Record<string, boolean>>(() => (strategies[0] ? { [strategies[0].id]: true } : {}));
  const size = fieldSizeM(result.selection.area_ha);
  const series = result.time_series ?? [];

  const choices = [
    horizon ? `Looking ahead ${yearsText(horizon)}.` : null,
    priorities ? `Priorities: ${priorityText(priorities)}.` : null,
    "Scores compare options for this field only.",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <>
      {result.warnings && result.warnings.length > 0 && (
        <Note tone="warning" title="Keep in mind">
          <ul>
            {result.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Note>
      )}

      <section className={s.section} aria-labelledby="strategies-title">
        <div>
          <h2 id="strategies-title" className={s.h2}>
            Rotation strategies
          </h2>
          <p className={s.muted}>{choices}</p>
        </div>
        {strategies.map((st, i) => (
          <StrategyCard
            key={st.id}
            strategy={st}
            index={i}
            baselineScore={baseline}
            open={!!open[st.id]}
            onToggle={() => setOpen((o) => ({ ...o, [st.id]: !o[st.id] }))}
          />
        ))}
      </section>

      {series.length > 0 && (
        <section className={s.section} aria-labelledby="history-title">
          <h2 id="history-title" className={s.h2}>
            Recent history
          </h2>
          <div className={s.charts}>
            {series.map((ts) => (
              <TimeSeriesChart key={ts.key} series={ts} />
            ))}
          </div>
        </section>
      )}

      <section className={s.section} aria-labelledby="conditions-title">
        <h2 id="conditions-title" className={s.h2}>
          Current conditions
        </h2>
        <MetricGroups metrics={result.current_conditions} fieldSizeM={size} headingLevel={3} />
      </section>

      <DatasetList datasets={result.datasets_used} />

      <Note>
        <div>{result.disclaimer}</div>
        <div className={s.fine}>
          Model {result.model_version}. Created {formatDateTime(result.generated_at)}.
        </div>
      </Note>
    </>
  );
}
