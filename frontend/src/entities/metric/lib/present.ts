import type { Metric } from "@/shared/api";
import { formatDate, formatDistance, toDisplay } from "@/shared/lib";

export type QualityTone = "success" | "info" | "warning" | "neutral";

/** Every metric shows how it was obtained. Text carries the meaning; tone only supports it. */
export const QUALITY: Record<Metric["quality"], { label: string; tone: QualityTone }> = {
  measured: { label: "Measured", tone: "success" },
  modeled: { label: "Modeled", tone: "info" },
  estimated: { label: "Estimate", tone: "warning" },
  unavailable: { label: "Not available", tone: "neutral" },
};

export type PresentedMetric = {
  key: string;
  label: string;
  available: boolean;
  value: string;
  unit: string;
  quality: { label: string; tone: QualityTone };
  when: string;
  source: string;
  pixel: string | null;
  /** The data cell is wider than this field: one reading covers many fields. */
  coarse: boolean;
  /** Backend note, or the reason a value is unavailable. */
  note: string | null;
};

const shortFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

function whenText(m: Metric): string {
  if (m.period?.start && m.period.end) {
    return `${shortFmt.format(new Date(`${m.period.start}T00:00:00Z`))} to ${formatDate(m.period.end)}`;
  }
  return m.as_of ? `As of ${formatDate(m.as_of)}` : "Long-term value";
}

/** Warn when the data cell is larger than the field (contract: resolution_m vs field size). */
export const isCoarse = (resolutionM: number | null | undefined, fieldSizeM: number | null) =>
  resolutionM != null && fieldSizeM != null && resolutionM > fieldSizeM;

/** One contract Metric as a card shows it. Never hides or invents a value. */
export function presentMetric(m: Metric, fieldSizeM: number | null): PresentedMetric {
  const available = m.quality !== "unavailable" && m.value !== null;
  const display = available ? toDisplay(m.value as number | string, m.unit) : { value: "Not available", unit: "" };
  return {
    key: m.key,
    label: m.label,
    available,
    value: display.value,
    unit: display.unit,
    quality: QUALITY[m.quality] ?? { label: "Unknown", tone: "neutral" },
    when: whenText(m),
    source: `${m.source.dataset}, ${m.source.provider}`,
    pixel: m.resolution_m ? `Pixel about ${formatDistance(m.resolution_m)}` : null,
    coarse: available && isCoarse(m.resolution_m, fieldSizeM),
    note: available ? (m.note ?? null) : m.unavailable_reason || "Not available right now.",
  };
}

const GROUPS: { category: string; title: string }[] = [
  { category: "moisture", title: "Moisture" },
  { category: "atmosphere", title: "Air" },
  { category: "temperature", title: "Temperature" },
  { category: "precipitation", title: "Rain" },
  { category: "soil", title: "Soil" },
  { category: "terrain", title: "Terrain" },
  { category: "vegetation", title: "Plants" },
];

export type MetricGroup = { category: string; title: string; metrics: Metric[] };

/** Metrics grouped by category in the design's order. Unknown categories go last, never dropped. */
export function groupMetrics(metrics: readonly Metric[]): MetricGroup[] {
  const known = GROUPS.map((g) => ({ ...g, metrics: metrics.filter((m) => m.category === g.category) }));
  const knownSet = new Set(GROUPS.map((g) => g.category));
  const others = metrics.filter((m) => !knownSet.has(m.category));
  const extra = others.length ? [{ category: "other", title: "Other", metrics: others }] : [];
  return [...known, ...extra].filter((g) => g.metrics.length > 0);
}
