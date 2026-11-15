import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import type { DatasetRef, Metric } from "@/shared/api";
import { Badge, Skeleton } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { SectionTitle } from "@/shared/ui/layout";
import { TermText } from "@/shared/ui/term-text";
import { GLOSSARY, HINTS, readingFor } from "../lib/glossary";
import { groupMetrics, presentMetric } from "../lib/present";
import { buildSourceRegistry, type SourceEntry, type SourceRegistry } from "../lib/sources";
import s from "./metric-card.module.css";

type CardProps = {
  metric: Metric;
  fieldSizeM: number | null;
  /** Numbered source for the chip. Without it, the card shows the dataset as text. */
  source?: SourceEntry;
  /** Plain-language reading under the value. */
  reading?: string;
  hintOpen?: boolean;
  onToggleHint?: () => void;
};

/**
 * One measure as a tile: label (+ info hint for NDVI, ET and anomaly) with the quality pill, the value with its
 * unit, a plain-language reading, then date · source · pixel size, coarse warning and notes in the footer.
 * Tiles sit in a responsive grid: three across on wide screens, one on phones.
 */
export function MetricCard({ metric, fieldSizeM, source, reading, hintOpen = false, onToggleHint }: CardProps) {
  const m = presentMetric(metric, fieldSizeM);
  const hint = HINTS[m.key];
  const hintId = `hint-${m.key}`;
  return (
    <article className={s.card} data-quality={metric.quality} aria-labelledby={`metric-${m.key}`}>
      <div className={s.head}>
        <h3 id={`metric-${m.key}`} className={s.label}>
          <TermText>{m.label}</TermText>
        </h3>
        {hint && onToggleHint && (
          <button
            type="button"
            className={s.hintBtn}
            aria-label={`What is ${m.label}?`}
            aria-expanded={hintOpen}
            aria-controls={hintId}
            onClick={onToggleHint}
          >
            <Icon name="help" size={20} />
          </button>
        )}
      </div>
      <div className={s.valueRow}>
        <span className={m.available ? s.value : s.valueMissing}>{m.value}</span>
        {m.unit && (
          <span className={s.unit}>
            <TermText>{m.unit}</TermText>
          </span>
        )}
        <span className={s.quality}>
          <Badge tone={m.quality.tone}>
            <TermText>{m.quality.label}</TermText>
          </Badge>
        </span>
      </div>
      {reading && (
        <div className={s.reading}>
          <TermText>{reading}</TermText>
        </div>
      )}
      {hint && hintOpen && (
        <div id={hintId} role="note" className={s.hint}>
          <div>
            <strong>What it is.</strong> <TermText>{hint.what}</TermText>
          </div>
          <div>
            <strong>How to read it.</strong> <TermText>{hint.read}</TermText>
          </div>
          <a href={`#${hint.glossaryId}`} className={s.link}>
            See it in the glossary
          </a>
        </div>
      )}
      <div className={s.metaCol}>
        {m.note && (
          <div className={s.note}>
            <TermText>{m.note}</TermText>
          </div>
        )}
        {m.coarse && (
          <div className={s.coarse}>
            <Icon name="warning" size={16} />
            <span>Wider than this field. One reading covers many fields around it.</span>
          </div>
        )}
        <div className={s.metaLine}>
          <span>{m.when}</span>
          <span aria-hidden="true">·</span>
          {source ? (
            <a
              href={`#${source.anchor}`}
              className={s.chip}
              aria-label={`Source ${source.n}: ${source.dataset}, ${source.provider}`}
            >
              [{source.n}] {source.short}
            </a>
          ) : (
            <span>{m.source}</span>
          )}
          {m.pixel && (
            <>
              <span aria-hidden="true">·</span>
              <span>
                <TermText>{m.pixel}</TermText>
              </span>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

const groupId = (category: string) => `metrics-${category}`;

/**
 * Metrics in category sections ("Moisture", "Air", ...), as on the Field and Analysis pages.
 * A row of chips above them jumps to each group, which saves a long scroll on phones.
 */
export function MetricGroups({
  metrics,
  fieldSizeM,
  registry,
  headingLevel = 2,
}: {
  metrics: readonly Metric[];
  fieldSizeM: number | null;
  /** Numbered sources; build once per page with `useSourceRegistry` so chips and the list agree. */
  registry?: SourceRegistry;
  headingLevel?: 2 | 3;
}) {
  // One hint open at a time.
  const [hint, setHint] = useState<string | null>(null);
  const groups = groupMetrics(metrics);
  return (
    <>
      {groups.length > 1 && (
        <nav className={s.jump} aria-label="Jump to a group of values">
          {groups.map((g) => (
            <a key={g.category} href={`#${groupId(g.category)}`} className={s.jumpLink}>
              <span className={s.dot} data-category={g.category} aria-hidden="true" />
              {g.title}
              <span className={s.jumpCount} aria-hidden="true">
                {g.metrics.length}
              </span>
            </a>
          ))}
        </nav>
      )}
      <div className={s.groups}>
        {groups.map((g) => (
          <section key={g.category} id={groupId(g.category)} className={s.group} aria-label={g.title}>
            <div className={s.groupHead}>
              <span className={s.dot} data-category={g.category} aria-hidden="true" />
              <SectionTitle as={headingLevel === 2 ? "h2" : "h3"} className={s.groupTitle}>
                {g.title}
              </SectionTitle>
              <span className={s.groupCount}>
                {g.metrics.length} {g.metrics.length === 1 ? "value" : "values"}
              </span>
            </div>
            <div className={s.rows}>
              {g.metrics.map((m) => (
                <MetricCard
                  key={m.key}
                  metric={m}
                  fieldSizeM={fieldSizeM}
                  source={registry?.forMetric(m.key)}
                  reading={readingFor(m, metrics)}
                  hintOpen={hint === m.key}
                  onToggleHint={() => setHint((h) => (h === m.key ? null : m.key))}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}

/** Numbered source registry for one page: metric sources first, then any extra datasets. */
export function useSourceRegistry(metrics: readonly Metric[], extra?: readonly DatasetRef[]): SourceRegistry {
  return useMemo(() => buildSourceRegistry(metrics, extra), [metrics, extra]);
}

/** "Where this data comes from" strip above the metrics, with links to the Sources list and the Glossary. */
export function SourcesStrip({ registry }: { registry: SourceRegistry }) {
  if (registry.list.length === 0) return null;
  return (
    <div className={s.strip}>
      <span className={s.stripTitle}>Where this data comes from</span>
      <span className={s.stripLine}>{registry.sourcesLine}</span>
      <a href="#sources" className={s.stripLink}>
        All {registry.list.length} {registry.list.length === 1 ? "source" : "sources"}
      </a>
      <a href="#glossary" className={s.stripLink}>
        Glossary
      </a>
    </div>
  );
}

/**
 * A box with a heading that opens and closes; closed by default. A link to the box or to anything inside it
 * (the strip links, source chips, "See it in the glossary") opens it first, so the jump lands on visible content.
 */
function CollapsibleBox({ id, titleId, title, children }: { id: string; titleId: string; title: string; children: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const openFor = (hash: string) => {
      const box = ref.current;
      if (!box || hash.length < 2) return;
      const target = document.getElementById(decodeURIComponent(hash.slice(1)));
      if (target && (target.contains(box) || box.contains(target))) box.open = true;
    };
    // Capture phase: open before the browser scrolls to the anchor.
    const onClick = (e: MouseEvent) => {
      const link = e.target instanceof Element ? e.target.closest("a[href^='#']") : null;
      if (link) openFor(link.getAttribute("href") ?? "");
    };
    const onHash = () => openFor(window.location.hash);
    onHash();
    document.addEventListener("click", onClick, true);
    window.addEventListener("hashchange", onHash);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);
  return (
    <section id={id} aria-labelledby={titleId} className={s.box}>
      <details ref={ref} className={s.collapse}>
        <summary className={s.collapseSummary}>
          <SectionTitle id={titleId}>{title}</SectionTitle>
          <span className={s.collapseIcon}>
            <Icon name="chevron" size={20} />
          </span>
        </summary>
        <div className={s.collapseBody}>{children}</div>
      </details>
    </section>
  );
}

/** Full Sources list; each card's chip number points here. */
export function SourcesList({ registry }: { registry: SourceRegistry }) {
  if (registry.list.length === 0) return null;
  return (
    <CollapsibleBox id="sources" titleId="sources-h" title="Where this data comes from">
      <p className={s.boxLead}>
        Each number above points to one or more of these sources. The number in brackets is the same here and on the
        card.
      </p>
      <ol className={s.sources}>
        {registry.list.map((e) => (
          <li key={e.anchor} id={e.anchor} className={s.sourceItem}>
            <span className={s.sourceN}>[{e.n}]</span>
            <div className={s.sourceBody}>
              <div className={s.sourceName}>{e.dataset}</div>
              <div className={s.sourceMeta}>{[e.provider, ...e.detail].join(" · ")}</div>
              {e.what && <div className={s.sourceWhat}>{e.what}</div>}
              {e.usedFor.length > 0 && <div className={s.sourceMeta}>Used for: {e.usedFor.join(", ")}</div>}
              {e.url && (
                <a href={e.url} target="_blank" rel="noopener noreferrer" className={s.sourceUrl}>
                  {e.host} (opens in a new tab)
                </a>
              )}
            </div>
          </li>
        ))}
      </ol>
    </CollapsibleBox>
  );
}

/** Glossary of the terms the cards and hints use; each term popover links to its entry here. */
export function Glossary() {
  return (
    <CollapsibleBox id="glossary" titleId="glossary-h" title="Glossary">
      <dl className={s.glossary}>
        {GLOSSARY.map((t) => (
          <div key={t.id} id={t.id} className={s.term}>
            <dt>{t.term}</dt>
            <dd>{t.def}</dd>
            <dd className={s.termWhy}>
              <strong>Why it matters.</strong> {t.why}
            </dd>
          </div>
        ))}
      </dl>
    </CollapsibleBox>
  );
}

/** Six grey blocks while metrics load. */
export function MetricGridSkeleton() {
  return (
    <div className={s.grid} aria-hidden="true">
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} height={168} />
      ))}
    </div>
  );
}
