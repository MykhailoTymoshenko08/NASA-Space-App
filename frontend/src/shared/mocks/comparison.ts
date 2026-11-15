import type { components } from "@/shared/api";
import { metricsFor, nearestCounty } from "./data";

type S = components["schemas"];

/** Demo land data only. Financial values stay unavailable without the real budget service. */
export function comparisonFor(fields: S["SavedField"][], request: S["SavedFieldComparisonRequest"]): S["FieldComparison"] {
  const now = new Date().toISOString();
  const rows: S["ComparisonRow"][] = [];
  const row = (key: string, label: string, group: S["ComparisonRow"]["group"], unit: string,
    value: (field: S["SavedField"]) => number | string | null) => {
    const cells: S["ComparisonCell"][] = fields.map((f) => {
      const v = value(f);
      return { saved_field_id: f.id, value: v, quality: v === null ? "unavailable" : "estimated",
        note: v === null ? "Not available in this demo. Connect to the API for budgets and survey data." : "Demo data only." };
    });
    rows.push({ key, label, group, unit, better: "none", cells, best: [],
      same_for_all: cells.every((cell) => cell.value !== null && cell.value === cells[0]?.value) });
  };
  row("net_return_per_acre", "Return after rent, per acre", "money", "USD/acre/year", () => null);
  row("rent", "Cash rent used", "money", "USD/acre/year", (f) => request.rent_per_acre?.[f.id] ?? null);
  row("area", "Field size", "land", "ha", (f) => f.area_ha);
  for (const [key, label, unit] of [["soil_organic_matter_pct", "Organic matter", "%"], ["soil_ph", "Soil pH", "pH"], ["soil_texture_class", "Soil texture", "class"]]) {
    row(key!, label!, "soil", unit!, (f) => metricsFor(f.centroid).find((m) => m.key === key)?.value ?? null);
  }
  row("latest_crop", "Last crop", "history", "class", (f) => f.crop_history?.[0]?.crop ?? null);
  return {
    generated_at: now, plan: request.plan ?? { rotation: ["corn", "soybean"], horizon_years: 2 }, rows,
    fields: fields.map((f, index) => ({
      saved_field_id: f.id, label: "ABCD"[index] as S["ComparedField"]["label"], name: f.name,
      field_id: f.field_id, state: f.state, county: nearestCounty(f.centroid), anchor: f.centroid,
      boundary_type: f.geometry.type === "Point" ? "buffered_point" : "estimated_csb", area_ha: f.area_ha,
      rent: { per_acre: request.rent_per_acre?.[f.id] ?? null,
        source: request.rent_per_acre?.[f.id] != null ? "farmer" : "none", is_placeholder: false },
      budget: null, net_return_per_acre: null, net_return_field: null, break_even_rent_per_acre: null,
      history: { source: "none", years_recorded: 0, first_year: null, latest_year: null, latest_crop: null,
        corn_years: 0, soybean_years: 0, other_years: 0, distinct_crops: 0, corn_in_a_row: 0, pattern: "unknown" },
      strengths: [], cautions: ["Demo data only. Use the connected API to compare real field budgets."],
      data_as_of: now, info_as_of: null,
    })),
    best: { net_return: [], soil_productivity: [], rent_value: [] },
    warnings: ["Demo only: soil values are sample data. Financial estimates require the connected API."],
    disclaimer: "Demo comparison. Do not use sample data to make lease decisions.",
  };
}
