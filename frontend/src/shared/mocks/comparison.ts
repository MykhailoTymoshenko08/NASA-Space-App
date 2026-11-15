/**
 * Demo POST /comparisons/saved-fields. Land, soil and history rows follow the backend rules
 * (backend/app/comparisons/saved.py) on sample values that vary per field (seeded by its id, so they stay
 * stable), and rows are ranked here as the server would. Financial estimates are withheld: budgets, returns and
 * state rents need the connected API. Only the farmer's own asking rent is echoed back.
 */
import type { components } from "@/shared/api";
import { nearestCounty } from "./data";

type S = components["schemas"];
type Cell = S["ComparisonCell"];
type Row = S["ComparisonRow"];

const DEMO_NOTE = "Demo data only.";
const NO_DEMO_MONEY = "Not available in this demo. Connect to the API for budgets and survey data.";
const PATTERN_LABELS: Record<S["CropHistorySummary"]["pattern"], string> = {
  corn_soybean: "Corn and soybeans in turn",
  continuous_corn: "Corn after corn",
  continuous_soybean: "Soybeans after soybeans",
  mixed: "Mixed crops",
  unknown: "Not enough years on record",
};
const DEMO_HISTORY = [
  { year: 2025, crop: "Corn" },
  { year: 2024, crop: "Soybeans" },
  { year: 2023, crop: "Corn" },
];
const TEXTURES = ["Silty clay loam", "Clay loam", "Loam", "Silt loam"];
const DRAINAGE = ["Poorly drained", "Somewhat poorly drained", "Moderately well drained", "Well drained"];

/** Stable pseudo-random numbers in [0, 1) per field id. */
function seeded(id: string) {
  let h = 2166136261;
  for (const ch of id) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  const seed = (h >>> 0) % 100_000;
  return (k: number) => {
    const x = Math.sin(seed * 0.0137 + k * 78.233) * 43758.5453;
    return x - Math.floor(x);
  };
}
const round = (v: number, d = 0) => Math.round(v * 10 ** d) / 10 ** d;

function summarize(saved: S["SavedField"]): S["CropHistorySummary"] {
  const own = saved.crop_history && saved.crop_history.length > 0;
  const years = [...(own ? saved.crop_history! : saved.field_id ? DEMO_HISTORY : [])].sort((a, b) => b.year - a.year);
  const crops = years.map((y) => y.crop);
  let cornRun = 0;
  while (crops[cornRun] === "Corn") cornRun++;
  const recent = crops.slice(0, 4);
  const pattern: S["CropHistorySummary"]["pattern"] =
    years.length < 2
      ? "unknown"
      : cornRun >= 3 || recent.every((c) => c === "Corn")
        ? "continuous_corn"
        : recent.every((c) => c === "Soybeans")
          ? "continuous_soybean"
          : recent.every((c, i) => (c === "Corn" || c === "Soybeans") && (i === 0 || c !== recent[i - 1]))
            ? "corn_soybean"
            : "mixed";
  return {
    source: years.length === 0 ? "none" : own ? "farmer" : "usda_csb",
    years_recorded: years.length,
    first_year: years.at(-1)?.year ?? null,
    latest_year: years[0]?.year ?? null,
    latest_crop: crops[0] ?? null,
    corn_years: crops.filter((c) => c === "Corn").length,
    soybean_years: crops.filter((c) => c === "Soybeans").length,
    other_years: crops.filter((c) => c !== "Corn" && c !== "Soybeans").length,
    distinct_crops: new Set(crops).size,
    corn_in_a_row: cornRun,
    pattern,
  };
}

const numeric = (cells: Cell[]) =>
  cells.flatMap((c) => (c.quality !== "unavailable" && typeof c.value === "number" ? [[c.saved_field_id, c.value] as const] : []));

/** Ids with the best value; empty when fewer than two values compare or all of them tie. */
function bestOf(cells: Cell[], better: Row["better"], target?: S["ValueRange"]): string[] {
  const values = numeric(cells);
  if (better === "none" || values.length < 2) return [];
  const score = (v: number) =>
    better === "higher" ? v : better === "lower" ? -v : -Math.max(target!.min - v, 0, v - target!.max);
  const top = Math.max(...values.map(([, v]) => score(v)));
  const best = values.filter(([, v]) => Math.abs(score(v) - top) < 1e-9).map(([id]) => id);
  return best.length === values.length ? [] : best;
}

const sameForAll = (cells: Cell[]) =>
  cells.length >= 2 && cells.every((c) => c.quality !== "unavailable" && c.value === cells[0]!.value);

function row(
  key: string,
  label: string,
  group: Row["group"],
  unit: string,
  better: Row["better"],
  cells: Cell[],
  note: string | null = null,
  target: S["ValueRange"] | null = null,
): Row {
  return { key, label, group, unit, better, target, cells, best: bestOf(cells, better, target ?? undefined), same_for_all: sameForAll(cells), note };
}

const cell = (id: string, value: number | string | null, quality: Cell["quality"], note: string | null = null, missing = "Not available."): Cell =>
  value === null ? { saved_field_id: id, value: null, quality: "unavailable", note: missing } : { saved_field_id: id, value, quality, note };

export function comparisonFor(saved: S["SavedField"][], req: S["SavedFieldComparisonRequest"]): S["FieldComparison"] {
  const plan: S["ComparisonPlan"] = {
    rotation: req.plan?.rotation ?? ["corn", "soybean"],
    horizon_years: req.plan?.horizon_years ?? 2,
  };

  const computed = saved.map((f, i) => {
    const r = seeded(f.id);
    const history = summarize(f);
    const rentPerAcre = req.rent_per_acre?.[f.id] ?? null;
    const nccpi = round(58 + 30 * r(1));
    return {
      f,
      label: "ABCD"[i] as S["ComparedField"]["label"],
      history,
      rent: { per_acre: rentPerAcre, source: rentPerAcre !== null ? "farmer" : "none", is_placeholder: false } as S["RentUsed"],
      nccpi,
      perPoint: rentPerAcre !== null ? round(rentPerAcre / nccpi, 2) : null,
      om: round(2.4 + 2.4 * r(2), 1),
      ph: round(5.7 + 1.6 * r(3), 1),
      texture: TEXTURES[Math.floor(r(4) * TEXTURES.length)]!,
      drainage: DRAINAGE[Math.floor(r(5) * DRAINAGE.length)]!,
      slope: round(0.6 + 7 * r(6) ** 2, 1),
      precip: round(860 + 80 * r(7)),
      temp: round(9.2 + 1.2 * r(8), 1),
    };
  });

  type C = (typeof computed)[number];
  const est = "estimated" as const;
  const each = (pick: (c: C) => number | string | null, quality: Cell["quality"], note: (c: C) => string | null = () => null, missing?: string) =>
    computed.map((c) => cell(c.f.id, pick(c), quality, note(c), missing));
  const historyNote = (c: C) =>
    c.history.source === "none" ? null : `${c.history.source === "farmer" ? "Your record" : "USDA crop maps"}, ${c.history.first_year} to ${c.history.latest_year}.`;
  const regional = "Regional climate: grid cells are much larger than a field.";

  const rows: Row[] = [
    row("net_return_per_acre", "Return after rent, per acre", "money", "USD/acre/year", "higher", each(() => null, est, () => null, NO_DEMO_MONEY),
      "Illustrative budget at base prices, average per year over the plan. Yields and prices are state references, the same for every field in a state."),
    row("net_return_field", "Return after rent, whole field", "money", "USD/year", "higher", each(() => null, est, () => null, NO_DEMO_MONEY),
      "Per-acre return times the estimated field area."),
    row("break_even_rent", "Highest rent the field can carry", "money", "USD/acre/year", "higher", each(() => null, est, () => null, NO_DEMO_MONEY),
      "Return before land at base prices: rent above this loses money in an average year."),
    row("rent", "Cash rent used", "money", "USD/acre/year", "lower",
      each((c) => c.rent.per_acre, est, () => "Your asking rent.", "Enter an asking rent. Demo mode has no state reference.")),
    row("rent_per_productivity_point", "Rent per soil productivity point", "money", "USD/acre/point", "lower", each((c) => c.perPoint, est, () => DEMO_NOTE, "Needs an asking rent."),
      "Rent divided by the NCCPI rating. Lower means more soil for the money."),
    row("area", "Field size", "land", "ha", "none",
      each((c) => c.f.area_ha, est, () => DEMO_NOTE, "Saved as a point: no field area.")),
    row("slope", "Slope", "land", "%", "lower", each((c) => c.slope, "measured", () => DEMO_NOTE)),
    row("land_cover", "Land cover", "land", "class", "none", each(() => "Cultivated crops", "measured", () => DEMO_NOTE)),
    row("soil_productivity_nccpi", "Soil productivity (NCCPI)", "soil", "index", "higher", each((c) => c.nccpi, "measured", () => DEMO_NOTE),
      "USDA rating from 0 to 100 for non-irrigated commodity crops. Higher is better."),
    row("soil_organic_matter_pct", "Organic matter", "soil", "%", "higher", each((c) => c.om, "measured", () => DEMO_NOTE)),
    row("soil_ph", "Soil pH", "soil", "pH", "target", each((c) => c.ph, "measured", () => DEMO_NOTE),
      "Most corn and soybean ground does best between pH 6.0 and 7.0.", { min: 6, max: 7 }),
    row("soil_texture_class", "Soil texture", "soil", "class", "none", each((c) => c.texture, "measured", () => DEMO_NOTE)),
    row("soil_drainage", "Drainage class", "soil", "class", "none", each((c) => c.drainage, "measured", () => DEMO_NOTE),
      "Poorly drained soils can be very productive when tiled. Ask about drainage tile."),
    row("rotation_pattern", "Recent rotation", "history", "class", "none",
      each((c) => (c.history.source === "none" ? null : PATTERN_LABELS[c.history.pattern]), est, historyNote, "No crop history on record.")),
    row("latest_crop", "Last crop", "history", "class", "none", each((c) => c.history.latest_crop, est, historyNote, "No crop history on record.")),
    row("corn_in_a_row", "Corn years in a row", "history", "years", "lower",
      each((c) => (c.history.source === "none" ? null : c.history.corn_in_a_row), est, historyNote, "No crop history on record."),
      "Corn after corn usually needs more nitrogen and has more pest pressure."),
    row("precipitation_normal", "Rain per year, long-term", "climate", "mm", "none", each((c) => c.precip, "modeled", () => DEMO_NOTE), regional),
    row("temperature_normal", "Average temperature, long-term", "climate", "degC", "none", each((c) => c.temp, "modeled", () => DEMO_NOTE), regional),
  ];
  const wins = (key: string, id: string) => rows.find((x) => x.key === key)!.best.includes(id);

  const fields: S["ComparedField"][] = computed.map((c) => {
    const id = c.f.id;
    const strengths: string[] = [];
    const cautions: string[] = [];
    if (wins("soil_productivity_nccpi", id)) strengths.push(`Most productive soil of these fields (NCCPI ${c.nccpi}).`);
    if (wins("rent_per_productivity_point", id)) strengths.push("Lowest rent for each point of soil productivity.");
    if (c.history.pattern === "corn_soybean") strengths.push("Corn and soybeans in turn: corn after soybeans needs less nitrogen.");
    if (c.history.corn_in_a_row >= 3) cautions.push(`Corn ${c.history.corn_in_a_row} years in a row: expect higher nitrogen needs and pest pressure.`);
    if (c.slope >= 6) cautions.push(`Slope about ${c.slope}%: check erosion control (terraces, waterways).`);
    if (c.f.geometry.type === "Point") cautions.push("No mapped field boundary: soil is read around a point, not over the field.");
    cautions.push("Demo data only. Use the connected API to compare real field budgets.");
    return {
      saved_field_id: id,
      label: c.label,
      name: c.f.name,
      field_id: c.f.field_id,
      state: c.f.state,
      county: (({ fips, name, state_postal }) => ({ fips, name, state_postal }))(nearestCounty(c.f.centroid)),
      anchor: c.f.centroid,
      boundary_type: c.f.geometry.type === "Point" ? "buffered_point" : "estimated_csb",
      area_ha: c.f.area_ha,
      rent: c.rent,
      budget: null,
      net_return_per_acre: null,
      net_return_field: null,
      break_even_rent_per_acre: null,
      history: c.history,
      strengths,
      cautions,
      data_as_of: new Date().toISOString(),
      info_as_of: c.f.info_fetched_at,
    };
  });

  const warnings = ["Demo only: soil values are sample data. Financial estimates require the connected API."];
  const best = (key: string) => rows.find((x) => x.key === key)!.best;
  return {
    generated_at: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
    plan,
    fields,
    rows,
    best: { net_return: best("net_return_per_acre"), soil_productivity: best("soil_productivity_nccpi"), rent_value: best("rent_per_productivity_point") },
    warnings,
    disclaimer: "Demo comparison. Do not use sample data to make lease decisions.",
  };
}
