import type { DatasetRef, Metric } from "@/shared/api";
import { formatDistance } from "@/shared/lib";
import { groupMetrics } from "./present";

/**
 * Plain-language facts about the public datasets the API cites. The contract only sends
 * `source: { dataset, provider, url }` per metric, so short names, update cadence and the
 * "what it is" line are matched here by dataset name. Unknown datasets still show, with
 * their own name and no extra text.
 */
type Descriptor = { match: RegExp; short: string; cadence: string; what: string };

const DESCRIPTORS: Descriptor[] = [
  {
    match: /SMAP\s*L3/i,
    short: "SMAP L3",
    cadence: "Every 2 to 3 days",
    what: "Moisture in the top few centimeters of soil, read by a satellite.",
  },
  {
    match: /SMAP\s*L4/i,
    short: "SMAP L4",
    cadence: "Daily",
    what: "Moisture down to about 1 meter, from a land model that blends in satellite readings.",
  },
  {
    match: /POWER.*(climatology|monthly|normal)/i,
    short: "POWER normals",
    cadence: "Long-term average",
    what: "What a normal year of rain looks like for this place.",
  },
  {
    match: /POWER/i,
    short: "NASA POWER",
    cadence: "Daily",
    what: "Daily weather from satellites and weather models: temperature, humidity and rain.",
  },
  {
    match: /SSURGO/i,
    short: "gSSURGO",
    cadence: "Updated yearly",
    what: "Mapped soil properties from the national soil survey. It is not a lab test of your field.",
  },
  {
    match: /SoilGrids/i,
    short: "SoilGrids",
    cadence: "Static global map",
    what: "Soil properties predicted worldwide from soil samples and satellite data. It is not a lab test of your field.",
  },
  {
    match: /3DEP/i,
    short: "3DEP",
    cadence: "Current survey",
    what: "Ground height and slope from airborne laser surveys.",
  },
  {
    match: /\bHLS\b|Harmonized Landsat/i,
    short: "HLS",
    cadence: "Every 2 to 5 days when skies are clear",
    what: "Satellite images used to measure how green the plants are.",
  },
  {
    match: /MOD16|evapotranspiration/i,
    short: "MODIS ET",
    cadence: "8-day totals",
    what: "Water leaving the land as plants and soil release it, estimated from satellite data.",
  },
  {
    match: /Crop Sequence Boundaries|\bCSB\b/i,
    short: "CSB",
    cadence: "Yearly",
    what: "Estimated field outlines and the crops mapped on them, from USDA satellite crop maps.",
  },
  {
    match: /Cropland Data Layer|\bCDL\b/i,
    short: "CDL",
    cadence: "Yearly",
    what: "A satellite map of which crop grew where, made every year by USDA.",
  },
];

const describe = (dataset: string) => DESCRIPTORS.find((d) => d.match.test(dataset)) ?? null;

/** Short chip text: the known short name, else the dataset name up to the first comma or bracket. */
function shortName(dataset: string): string {
  const d = describe(dataset);
  if (d) return d.short;
  const cut = dataset.split(/[,(]/)[0]!.trim();
  return cut.length > 24 ? `${cut.slice(0, 22).trimEnd()}…` : cut;
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 48);

export type SourceEntry = {
  /** Number in brackets, by first appearance on the page. */
  n: number;
  /** Element id of the entry in the Sources list. */
  anchor: string;
  dataset: string;
  provider: string;
  short: string;
  url: string | null;
  host: string;
  /** "Pixel about 5.6 mi", or the dataset's coverage period, or "". */
  detail: string[];
  what: string;
  /** Labels of the metrics that use it. Empty for datasets the analysis used without a card. */
  usedFor: string[];
};

export type SourceRegistry = {
  list: SourceEntry[];
  /** Lookup by metric key. */
  forMetric: (key: string) => SourceEntry | undefined;
  /**
   * One item per entry in `list`, so the count matches "All N sources":
   * "NASA POWER, gSSURGO (USDA NRCS) and 3DEP (USGS)". The provider is left out when the short name
   * already starts with it.
   */
  sourcesLine: string;
};

const keyOf = (dataset: string, provider: string) => `${provider}\u0000${dataset}`;

function joinAnd(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/**
 * One numbered entry per distinct dataset, in the order the metric groups show them,
 * then any extra datasets (e.g. AnalysisResult.datasets_used) that no metric cites.
 */
export function buildSourceRegistry(
  metrics: readonly Metric[],
  extra: readonly DatasetRef[] = [],
): SourceRegistry {
  const byKey = new Map<string, SourceEntry>();
  const byMetric = new Map<string, SourceEntry>();
  const resolution = new Map<string, number>();

  const add = (dataset: string, provider: string, url: string | null | undefined): SourceEntry => {
    const k = keyOf(dataset, provider);
    let e = byKey.get(k);
    if (!e) {
      const d = describe(dataset);
      e = {
        n: byKey.size + 1,
        anchor: `src-${byKey.size + 1}-${slug(dataset)}`,
        dataset,
        provider,
        short: shortName(dataset),
        url: url ?? null,
        host: url ? hostOf(url) : "",
        detail: [],
        what: d?.what ?? "",
        usedFor: [],
      };
      byKey.set(k, e);
    } else if (!e.url && url) {
      e.url = url;
      e.host = hostOf(url);
    }
    return e;
  };

  for (const g of groupMetrics(metrics)) {
    for (const m of g.metrics) {
      const e = add(m.source.dataset, m.source.provider, m.source.url);
      e.usedFor.push(m.label);
      byMetric.set(m.key, e);
      if (m.resolution_m != null) {
        const k = keyOf(e.dataset, e.provider);
        const prev = resolution.get(k);
        resolution.set(k, prev == null ? m.resolution_m : Math.min(prev, m.resolution_m));
      }
    }
  }

  for (const d of extra) {
    const k = keyOf(d.dataset, d.provider);
    const e = add(d.dataset, d.provider, d.url);
    if (d.resolution_m != null && !resolution.has(k)) resolution.set(k, d.resolution_m);
    if (d.coverage_period && !e.detail.includes(d.coverage_period)) e.detail.push(d.coverage_period);
  }

  const list = [...byKey.values()];
  for (const e of list) {
    const res = resolution.get(keyOf(e.dataset, e.provider));
    const cadence = describe(e.dataset)?.cadence;
    e.detail = [res != null ? `Pixel about ${formatDistance(res)}` : null, cadence ?? null, ...e.detail].filter(
      (x): x is string => !!x,
    );
  }

  const named = (e: SourceEntry) =>
    !e.provider || e.short.toLowerCase().startsWith(e.provider.toLowerCase()) ? e.short : `${e.short} (${e.provider})`;

  return { list, forMetric: (key) => byMetric.get(key), sourcesLine: joinAnd(list.map(named)) };
}
