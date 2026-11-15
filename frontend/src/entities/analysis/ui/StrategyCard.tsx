import { useId } from "react";
import type { Strategy } from "@/shared/api";
import { Button } from "@/shared/ui/button";
import { Badge } from "@/shared/ui/feedback";
import { MonoLabel } from "@/shared/ui/layout";
import { MeterBar } from "@/shared/ui/progress";
import { TermText } from "@/shared/ui/term-text";
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

/**
 * One rotation strategy: rank, name, summary, score, seasons and expandable reasons.
 * Summary and reasons mark known terms when a `TermsProvider` (e.g. `GlossaryTerms`) wraps the card.
 */
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
          <p>
            <TermText>{st.summary}</TermText>
          </p>
        </div>
        <div className={s.score}>
          <ScoreRing score={st.score} best={index === 0} />
          <div className={s.scoreText}>
            <div className={s.delta}>{deltaText(st, baselineScore)}</div>
            <div className={s.confidence}>{confidenceText(st.confidence)}</div>
          </div>
        </div>
      </div>

      {st.rotation.length > 0 && (
        <ol className={s.seasons} aria-label="Seasons in one rotation cycle">
          {[...st.rotation]
            .sort((a, b) => a.season_index - b.season_index)
            .map((r) => (
              <li key={r.season_index} className={s.season} data-role={r.role}>
                <span className={s.seasonWhen}>Season {r.season_index + 1}</span>
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
                      <div>
                        <TermText>{e.statement}</TermText>
                      </div>
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

/** Score out of 100 as a ring; the number inside is the text, the ring only supports it. */
function ScoreRing({ score, best }: { score: number; best: boolean }) {
  const value = Math.round(score);
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const r = 30;
  const c = 2 * Math.PI * r;
  return (
    <div className={`${s.ring} ${best ? s.ringBest : ""}`}>
      <svg viewBox="0 0 72 72" aria-hidden="true" className={s.ringSvg}>
        <circle cx="36" cy="36" r={r} className={s.ringTrack} />
        <circle
          cx="36"
          cy="36"
          r={r}
          className={s.ringValue}
          strokeDasharray={`${(c * pct).toFixed(1)} ${c.toFixed(1)}`}
          transform="rotate(-90 36 36)"
        />
      </svg>
      <div className={s.scoreValue}>
        {value}
        <span className={s.scoreMax}> / 100</span>
      </div>
    </div>
  );
}

function DetailList({ title, items }: { title: string; items: readonly string[] }) {
  if (items.length === 0) return null;
  return (
    <div className={s.detail}>
      <MonoLabel as="h4">{title}</MonoLabel>
      <ul className={s.bullets}>
        {items.map((t, i) => (
          <li key={i}>
            <TermText>{t}</TermText>
          </li>
        ))}
      </ul>
    </div>
  );
}
