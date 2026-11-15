import { useId } from "react";
import type { Strategy } from "@/shared/api";
import { Button } from "@/shared/ui/button";
import { Badge } from "@/shared/ui/feedback";
import { MonoLabel } from "@/shared/ui/layout";
import { MeterBar } from "@/shared/ui/progress";
import { CRITERION_LABEL, ROLE_LABEL } from "../config/labels";
import { confidenceText, datasetSource, deltaText, rankLabel } from "../lib/strategies";
import { StrategyBudget } from "./StrategyBudget";
import s from "./analysis.module.css";

type Props = {
  strategy: Strategy;
  index: number;
  baselineScore: number | null;
  open: boolean;
  onToggle: () => void;
};

/** One rotation strategy: rank, name, summary, score, seasons and expandable reasons. */
export function StrategyCard({ strategy: st, index, baselineScore, open, onToggle }: Props) {
  const detailsId = useId();
  const titleId = useId();
  return (
    <article className={`${s.strategy} ${index === 0 ? s.best : ""}`} aria-labelledby={titleId}>
      <div className={s.strategyTop}>
        <div className={s.strategyMain}>
          <div className={s.tags}>
            <Badge tone="neutral">{rankLabel(index)}</Badge>
            {st.is_current && <Badge tone="info">Your current rotation</Badge>}
            {st.needs_local_review && <Badge tone="warning">Local review advised</Badge>}
          </div>
          <h3 id={titleId} className={s.strategyName}>
            {st.name}
          </h3>
          <p>{st.summary}</p>
        </div>
        <div className={s.score}>
          <div className={s.scoreValue}>
            {Math.round(st.score)}
            <span className={s.scoreMax}> / 100</span>
          </div>
          <div className={s.muted}>{deltaText(st, baselineScore)}</div>
          <div className={s.confidence}>{confidenceText(st.confidence)}</div>
        </div>
      </div>

      {st.rotation.length > 0 && (
        <ol className={s.seasons} aria-label="Plantings in the rotation plan">
          {[...st.rotation]
            .sort((a, b) => a.season_index - b.season_index)
            .map((r) => (
              <li key={r.season_index} className={s.season}>
                <span className={s.seasonWhen}>
                  {r.year ? `Year ${r.year} · ${r.season === "cover" ? "cover crop" : "main crop"}` : `Season ${r.season_index + 1}`}
                </span>
                <span className={s.seasonCrop}>{r.crop}</span>
                <span className={s.seasonRole}>{ROLE_LABEL[r.role] ?? r.role}</span>
              </li>
            ))}
        </ol>
      )}

      {st.budget && <StrategyBudget budget={st.budget} />}

      <Button variant="secondary" className={s.toggle} onClick={onToggle} aria-expanded={open} aria-controls={detailsId}>
        {open ? "Hide details" : "Show details"}
      </Button>

      <div id={detailsId} hidden={!open} className={s.details}>
        {open && (
          <>
            <DetailList title="Good for" items={st.benefits} />
            <DetailList title="Watch out for" items={st.risks} />
            {st.score_breakdown && st.score_breakdown.length > 0 && (
              <div className={s.detail}>
                <MonoLabel as="h4">Fit by topic</MonoLabel>
                <ul className={s.breakdown}>
                  {st.score_breakdown.map((b) => (
                    <li key={b.criterion} className={s.breakdownRow}>
                      <span>{CRITERION_LABEL[b.criterion] ?? b.criterion}</span>
                      <MeterBar percent={b.score} />
                      <span className={s.breakdownScore}>{Math.round(b.score)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {st.evidence.length > 0 && (
              <div className={s.detail}>
                <MonoLabel as="h4">Why we suggest it</MonoLabel>
                <ul className={s.evidence}>
                  {st.evidence.map((e, i) => (
                    <li key={i}>
                      <div>{e.statement}</div>
                      {e.source && <div className={s.small}>{datasetSource(e.source)}</div>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <DetailList title="What we do not know" items={st.information_gaps} />
          </>
        )}
      </div>
    </article>
  );
}

function DetailList({ title, items }: { title: string; items: readonly string[] }) {
  if (items.length === 0) return null;
  return (
    <div className={s.detail}>
      <MonoLabel as="h4">{title}</MonoLabel>
      <ul className={s.bullets}>
        {items.map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ul>
    </div>
  );
}
