import type { Metric } from "@/shared/api";
import { Badge, Skeleton, type Tone } from "@/shared/ui/feedback";
import { Card, MonoLabel } from "@/shared/ui/layout";
import { groupSources, type SourceStatus } from "../lib/present";
import s from "./sources-list.module.css";

const STATUS: Record<SourceStatus, { tone: Tone; text: string }> = {
  done: { tone: "success", text: "Done" },
  partial: { tone: "info", text: "Partly answered" },
  "no-answer": { tone: "error", text: "No answer" },
};

type Props = { state: "loading" | "error" | { metrics: readonly Metric[] } };

/** "Where the numbers come from": one row per data source, with a text status. */
export function SourcesList({ state }: Props) {
  return (
    <Card compact as="section" aria-labelledby="sources-title">
      <MonoLabel as="h3" id="sources-title" className={s.title}>
        Where the numbers come from
      </MonoLabel>

      {state === "loading" && (
        <div className={s.list}>
          <Skeleton height={20} width="70%" />
          <Skeleton height={20} width="55%" />
          <span className="visually-hidden">Loading sources</span>
        </div>
      )}

      {state === "error" && <p className={s.muted}>Sources appear once our server answers.</p>}

      {typeof state === "object" && (
        <ul className={s.list}>
          {groupSources(state.metrics).map((row) => (
            <li key={row.name} className={s.row}>
              <span>
                {row.url ? (
                  <a href={row.url} target="_blank" rel="noreferrer" className={s.name}>
                    {row.name}
                  </a>
                ) : (
                  <strong className={s.name}>{row.name}</strong>
                )}{" "}
                <span className={s.muted}>{row.measures.join(", ")}</span>
              </span>
              <Badge tone={STATUS[row.status].tone}>{STATUS[row.status].text}</Badge>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
