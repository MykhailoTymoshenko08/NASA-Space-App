import type { Metric } from "@/shared/api";
import { formatDistance, toDisplay } from "@/shared/lib";

export type QualityBadge = { tone: "info" | "neutral"; text: string };

export type PresentedMetric =
  | {
      status: "ok";
      value: string;
      unit: string;
      badge: QualityBadge | null;
      when: string | null;
      sourceName: string;
      note: string | null;
      coarseWarning: string | null;
    }
  | { status: "unavailable"; sourceName: string; reason: string };

/** A metric is "much coarser" than the field when its grid cell is this many times the field's side. */
export const COARSE_FACTOR = 3;

const dateFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const shortFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const parseDate = (iso: string) => new Date(`${iso}T00:00:00Z`);

export const sourceName = (m: Metric) => {
  const { dataset, provider } = m.source;
  return dataset.toLowerCase().startsWith(provider.toLowerCase()) ? dataset : `${provider} ${dataset}`;
};

function whenText(m: Metric): string | null {
  if (m.period?.start && m.period.end) {
    return `Average, ${shortFmt.format(parseDate(m.period.start))} to ${dateFmt.format(parseDate(m.period.end))}`;
  }
  return m.as_of ? `As of ${dateFmt.format(parseDate(m.as_of))}` : null;
}

function badgeFor(m: Metric): QualityBadge | null {
  if (m.quality === "estimated") return { tone: "info", text: "Estimate" };
  if (m.quality === "modeled") return { tone: "neutral", text: "Modeled" };
  return null;
}

/** Warn when the data grid is much bigger than the field, so the value is a regional average. */
export function coarseWarning(resolutionM: number | null, fieldAreaHa: number | null): string | null {
  if (resolutionM == null || fieldAreaHa == null || fieldAreaHa <= 0) return null;
  const fieldSideM = Math.sqrt(fieldAreaHa * 10_000);
  if (resolutionM < fieldSideM * COARSE_FACTOR) return null;
  return `Coarse data: a regional average over about ${formatDistance(resolutionM)}, not just your field.`;
}

/** Turn one contract Metric into what a card shows. Never invents a value. */
export function presentMetric(m: Metric, fieldAreaHa: number | null): PresentedMetric {
  const name = sourceName(m);
  if (m.quality === "unavailable" || m.value === null) {
    return { status: "unavailable", sourceName: name, reason: m.unavailable_reason || "No reason was given." };
  }
  const display = toDisplay(m.value, m.unit);
  return {
    status: "ok",
    value: display.value,
    unit: display.unit,
    badge: badgeFor(m),
    when: whenText(m),
    sourceName: name,
    note: m.note ?? null,
    coarseWarning: coarseWarning(m.resolution_m, fieldAreaHa),
  };
}

export type SourceStatus = "done" | "partial" | "no-answer";
export type SourceRow = { name: string; url: string | null; measures: string[]; status: SourceStatus };

/** Group metrics by data source for the "Where the numbers come from" list. */
export function groupSources(metrics: readonly Metric[]): SourceRow[] {
  const rows = new Map<string, SourceRow & { ok: number; total: number }>();
  for (const m of metrics) {
    const name = sourceName(m);
    const row = rows.get(name) ?? { name, url: m.source.url ?? null, measures: [], status: "done", ok: 0, total: 0 };
    row.measures.push(m.label.toLowerCase());
    row.total += 1;
    if (m.quality !== "unavailable" && m.value !== null) row.ok += 1;
    rows.set(name, row);
  }
  return [...rows.values()].map(({ ok, total, ...row }) => ({
    ...row,
    status: ok === total ? "done" : ok === 0 ? "no-answer" : "partial",
  }));
}
