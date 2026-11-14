/**
 * Demo data for MSW, typed from the generated contract. Sample values only: never shipped as real data.
 */
import type { components } from "@/shared/api";

type S = components["schemas"];
type LatLon = S["LatLon"];

export const STATES: S["State"][] = [
  { fips: "17", name: "Illinois", postal: "IL", bbox: [-91.51, 36.97, -87.5, 42.51] },
  { fips: "19", name: "Iowa", postal: "IA", bbox: [-96.64, 40.37, -90.14, 43.5] },
  { fips: "31", name: "Nebraska", postal: "NE", bbox: [-104.05, 40.0, -95.31, 43.0] },
];

const county = (fips: string, name: string, st: S["State"], lat: number, lon: number): S["County"] => ({
  fips,
  name,
  state_fips: st.fips,
  state_postal: st.postal,
  bbox: [lon - 0.25, lat - 0.2, lon + 0.25, lat + 0.2],
  centroid: { lat, lon },
  has_field_coverage: true,
});
const [IL, IA, NE] = STATES as [S["State"], S["State"], S["State"]];

export const COUNTIES: S["County"][] = [
  county("17019", "Champaign", IL, 40.14, -88.2),
  county("17113", "McLean", IL, 40.49, -88.85),
  county("19013", "Black Hawk", IA, 42.47, -92.31),
  county("19153", "Polk", IA, 41.69, -93.57),
  county("19169", "Story", IA, 42.04, -93.46),
  county("31079", "Hall", NE, 40.87, -98.5),
  county("31109", "Lancaster", NE, 40.78, -96.69),
];

export const DEFAULT_POINT: LatLon = { lat: 41.5868, lon: -93.625 };

const CONUS = { west: -125, south: 24.5, east: -66.9, north: 49.5 };
export const inConus = (p: LatLon) =>
  p.lon >= CONUS.west && p.lon <= CONUS.east && p.lat >= CONUS.south && p.lat <= CONUS.north;

export const supportedStateAt = (p: LatLon) =>
  STATES.find((s) => {
    const [w = 0, so = 0, e = 0, n = 0] = s.bbox;
    return p.lon >= w && p.lat >= so && p.lon <= e && p.lat <= n;
  }) ?? null;

export function nearestCounty(p: LatLon): S["County"] {
  let best = COUNTIES[0]!;
  let d = Infinity;
  for (const c of COUNTIES) {
    const dd = (c.centroid.lat - p.lat) ** 2 + (c.centroid.lon - p.lon) ** 2;
    if (dd < d) {
      d = dd;
      best = c;
    }
  }
  return best;
}

/** A slightly skewed ~570 m square around the point (about 80 acres). */
function fieldPolygon(c: LatLon): S["GeoJSONPolygon"] {
  const dLat = 0.00256;
  const dLon = dLat / Math.cos((c.lat * Math.PI) / 180);
  const ring = [
    [c.lon - dLon, c.lat - dLat * 0.95],
    [c.lon + dLon * 1.04, c.lat - dLat],
    [c.lon + dLon, c.lat + dLat * 1.02],
    [c.lon - dLon * 0.98, c.lat + dLat],
  ];
  return { type: "Polygon", coordinates: [[...ring, ring[0]!]] };
}

function circlePolygon(c: LatLon, radiusM: number): S["GeoJSONPolygon"] {
  const dLat = radiusM / 111_320;
  const dLon = dLat / Math.cos((c.lat * Math.PI) / 180);
  const ring = Array.from({ length: 33 }, (_, i) => {
    const a = ((i % 32) / 32) * 2 * Math.PI;
    return [c.lon + dLon * Math.cos(a), c.lat + dLat * Math.sin(a)];
  });
  return { type: "Polygon", coordinates: [ring] };
}

/** Field id that encodes its point, so GET /fields/{id} can rebuild the same field. */
export const demoFieldId = (p: LatLon) =>
  `csb2025_demo${Math.round((p.lat + 90) * 10000)}x${Math.round((p.lon + 180) * 10000)}`;

export function pointOfFieldId(id: string): LatLon | null {
  const m = /^csb2025_demo(\d+)x(\d+)$/.exec(id);
  if (!m) return null;
  return { lat: Number(m[1]) / 10000 - 90, lon: Number(m[2]) / 10000 - 180 };
}

/** Inside IA/IL/NE: an estimated field area. Elsewhere in CONUS: a 300 m circle. */
export function selectionFor(
  p: LatLon,
  source: S["SelectionSource"],
  how: "id" | "point" = "point",
): S["FieldSelection"] {
  const c = nearestCounty(p);
  const countyRef = { fips: c.fips, name: c.name, state_postal: c.state_postal };
  if (!supportedStateAt(p)) {
    return {
      field_id: null,
      anchor: p,
      geometry: circlePolygon(p, 300),
      resolved_by: "buffered_point",
      boundary_type: "buffered_point",
      snap_distance_m: null,
      buffer_m: 300,
      area_ha: 28.3,
      crop_class: null,
      crop_history: [],
      county: countyRef,
      source,
    };
  }
  return {
    field_id: demoFieldId(p),
    anchor: p,
    geometry: fieldPolygon(p),
    resolved_by: how === "id" ? "field_polygon" : "snapped_point",
    boundary_type: "estimated_csb",
    snap_distance_m: how === "id" ? 0 : 120,
    buffer_m: null,
    area_ha: 32.4,
    crop_class: "Corn",
    crop_history: [
      { year: 2025, crop: "Corn" },
      { year: 2024, crop: "Soybeans" },
      { year: 2023, crop: "Corn" },
    ],
    county: countyRef,
    source,
  };
}

const NASA = "NASA";
const m = (
  key: string,
  label: string,
  category: S["Metric"]["category"],
  value: number | string | null,
  unit: string,
  quality: S["Metric"]["quality"],
  dataset: string,
  provider: string,
  resolution_m: number,
  extra: Partial<S["Metric"]> = {},
): S["Metric"] => ({
  key,
  label,
  category,
  value,
  unit,
  as_of: "2026-11-12",
  period: null,
  quality,
  unavailable_reason: null,
  source: { dataset, provider, url: null },
  resolution_m,
  note: null,
  ...extra,
});

/** Scenario: lat >= 45 has no SMAP pass (shows "Not available" with a reason). */
export function metricsFor(p: LatLon): S["Metric"][] {
  const smapDown = p.lat >= 45;
  return [
    smapDown
      ? m("soil_moisture_surface", "Soil moisture (surface)", "moisture", null, "m3/m3", "unavailable", "SMAP L3 Enhanced Soil Moisture", NASA, 9000, {
          as_of: null,
          unavailable_reason: "No satellite pass over this spot in the last 7 days.",
        })
      : m("soil_moisture_surface", "Soil moisture (surface)", "moisture", 0.27, "m3/m3", "measured", "SMAP L3 Enhanced Soil Moisture", NASA, 9000),
    m("soil_moisture_rootzone", "Soil moisture (root zone)", "moisture", 0.31, "m3/m3", "modeled", "SMAP L4 Soil Moisture", NASA, 9000),
    m("soil_wetness_surface", "Surface soil wetness (modeled, 30-day mean)", "moisture", 0.64, "fraction", "modeled", "NASA POWER", NASA, 55000),
    m("relative_humidity_2m", "Relative humidity", "atmosphere", 68, "%", "modeled", "NASA POWER", NASA, 50000),
    m("air_temp_mean_2m", "Air temperature (30-day mean)", "temperature", 13.9, "degC", "modeled", "NASA POWER", NASA, 50000),
    m("precip_30d_total", "Rain, last 30 days", "precipitation", 41, "mm", "modeled", "NASA POWER", NASA, 50000),
    m("precip_annual_normal", "Rain in a normal year", "precipitation", 910, "mm", "modeled", "NASA POWER climatology", NASA, 50000, { as_of: null }),
    m("soil_organic_matter_pct", "Soil organic matter", "soil", 3.8, "%", "measured", "gSSURGO", "USDA NRCS", 30, { as_of: null }),
    m("soil_nitrogen_total", "Soil nitrogen (total)", "soil", 1.9, "g/kg", "estimated", "Derived from soil organic matter", "Field Shift model", 30, {
      as_of: null,
      note: "Estimated from organic matter. This is not a soil lab test.",
    }),
    m("soil_ph", "Soil pH", "soil", 6.4, "pH", "measured", "gSSURGO", "USDA NRCS", 30, { as_of: null }),
    m("soil_texture_class", "Soil texture", "soil", "Silty clay loam", "class", "measured", "gSSURGO", "USDA NRCS", 30, { as_of: null }),
    m("elevation_m", "Elevation", "terrain", 286, "m", "measured", "3DEP elevation", "USGS", 10, { as_of: null }),
    m("slope_pct", "Slope", "terrain", 2.1, "%", "measured", "3DEP elevation", "USGS", 10, { as_of: null }),
    m("vegetation_index_ndvi", "Plant greenness (NDVI)", "vegetation", null, "none", "unavailable", "HLS Sentinel-2", NASA, 30, {
      as_of: null,
      unavailable_reason: "No cloud-free satellite pass in the last 14 days.",
    }),
  ];
}

const POWER: S["DatasetRef"] = { dataset: "NASA POWER", provider: NASA, resolution_m: 50000, coverage_period: "2015-2026" };
const SMAP: S["DatasetRef"] = { dataset: "SMAP L3 Enhanced Soil Moisture", provider: NASA, resolution_m: 9000, coverage_period: "2015-2026" };
const DEM: S["DatasetRef"] = { dataset: "3DEP elevation", provider: "USGS", resolution_m: 10, coverage_period: "Current" };
const CSB: S["DatasetRef"] = { dataset: "Crop Sequence Boundaries", provider: "USDA NASS", resolution_m: null, coverage_period: "2018-2025" };
const SSURGO: S["DatasetRef"] = { dataset: "gSSURGO soil survey", provider: "USDA NRCS", resolution_m: 30, coverage_period: "Current survey" };

const strategy = (s: Partial<S["Strategy"]> & Pick<S["Strategy"], "id" | "name" | "score">): S["Strategy"] => ({
  is_current: false,
  rotation: [],
  confidence: "medium",
  summary: "",
  benefits: [],
  risks: [],
  evidence: [],
  information_gaps: [],
  needs_local_review: false,
  ...s,
});

const breakdown = (v: number[]): S["Strategy"]["score_breakdown"] =>
  (["water_use", "soil_health", "erosion", "nitrogen", "pest_cycle", "income", "climate_risk"] as const).map((criterion, i) => ({
    criterion,
    score: v[i] ?? 50,
  }));

function weekly(n: number, f: (i: number) => number | null): { t: string; v: number | null }[] {
  const end = Date.UTC(2026, 10, 12);
  return Array.from({ length: n }, (_, i) => ({
    t: new Date(end - (n - 1 - i) * 7 * 86_400_000).toISOString().slice(0, 10),
    v: f(i),
  }));
}
const noise = (i: number, k: number) => {
  const x = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453;
  return x - Math.floor(x);
};

export function resultFor(selection: S["FieldSelection"]): S["AnalysisResult"] {
  return {
    selection,
    generated_at: new Date().toISOString(),
    model_version: "rotation-v0.1",
    current_conditions: metricsFor(selection.anchor),
    time_series: [
      {
        key: "soil_moisture_surface",
        label: "Soil moisture (surface)",
        unit: "m3/m3",
        source: { ...SMAP, dataset: "SMAP L3, weekly mean" },
        points: weekly(26, (i) => Math.round((0.31 - i * 0.0015 + (noise(i, 9) - 0.5) * 0.02) * 1000) / 1000),
      },
      {
        key: "precip_weekly_total",
        label: "Rain",
        unit: "mm",
        source: { ...POWER, dataset: "NASA POWER, weekly total" },
        points: weekly(26, (i) => (noise(i, 7) > 0.55 ? Math.round((6 + noise(i, 8) * 30) * 10) / 10 : 0)),
      },
    ],
    strategies: [
      strategy({
        id: "strat_corn_soy_cover",
        name: "Corn / soybean with winter rye cover",
        score: 82,
        confidence: "high",
        rotation: [
          { season_index: 0, crop: "Soybeans", role: "cash_crop" },
          { season_index: 1, crop: "Corn", role: "cash_crop" },
          { season_index: 2, crop: "Winter rye", role: "cover_crop" },
        ],
        score_breakdown: breakdown([78, 90, 88, 70, 75, 72, 80]),
        summary:
          "Keeps your two main crops and adds a rye cover after harvest. It protects the soil and holds water, for a small extra cost.",
        benefits: ["Less soil washed away on sloping ground", "Holds more water through dry spells", "Keeps both of your usual crops"],
        risks: ["Seed and seeding add cost", "Rye has to be ended on time in spring"],
        evidence: [
          { statement: "Slope is 2.1 percent, where cover crops cut soil loss at low cost.", metric_key: "slope_pct", source: DEM },
          {
            statement: "Surface soil moisture is 0.27 m³/m³ and has been falling, so ground cover helps keep water.",
            metric_key: "soil_moisture_surface",
            source: SMAP,
          },
        ],
        information_gaps: ["Your seeding and harvest dates are not known."],
      }),
      strategy({
        id: "strat_corn_soy_oats_clover",
        name: "Corn / soybean / oats with red clover",
        score: 77,
        rotation: [
          { season_index: 0, crop: "Corn", role: "cash_crop" },
          { season_index: 1, crop: "Soybeans", role: "cash_crop" },
          { season_index: 2, crop: "Oats", role: "cash_crop" },
          { season_index: 3, crop: "Red clover", role: "nitrogen_fixer" },
        ],
        score_breakdown: breakdown([74, 86, 80, 88, 90, 62, 76]),
        summary:
          "Adds oats and a clover that puts nitrogen back in the soil. Fewer pests and better soil, with lower income in the oat year.",
        benefits: ["Clover adds nitrogen for the next crop", "A longer cycle breaks pest build-up"],
        risks: ["Lower income in the oat year", "Needs a market or use for the oats"],
        evidence: [{ statement: "Your mapped crops repeat corn and soybeans, so a third crop breaks the cycle.", source: CSB }],
        information_gaps: ["Local oat prices are not included."],
      }),
      strategy({
        id: "strat_corn_soy_alfalfa",
        name: "Corn / soybean / alfalfa for forage",
        score: 70,
        confidence: "low",
        needs_local_review: true,
        rotation: [
          { season_index: 0, crop: "Corn", role: "cash_crop" },
          { season_index: 1, crop: "Soybeans", role: "cash_crop" },
          { season_index: 2, crop: "Alfalfa", role: "forage" },
          { season_index: 3, crop: "Alfalfa", role: "forage" },
        ],
        score_breakdown: breakdown([66, 84, 90, 86, 88, 48, 60]),
        summary: "Two years of alfalfa rebuild the soil and fix nitrogen. It only makes sense if you can use or sell the hay.",
        benefits: ["Strongest soil cover of the options", "Fixes nitrogen for the corn that follows"],
        risks: ["Needs hay equipment and a buyer"],
        evidence: [{ statement: "Soil organic matter is 3.8 percent, a good base for a deep-rooted forage.", source: SSURGO }],
        information_gaps: ["No hay or livestock market data for your county.", "Drainage of this field is not known."],
      }),
      strategy({
        id: "strat_current",
        name: "Corn / soybean (your current rotation)",
        score: 64,
        confidence: "high",
        is_current: true,
        rotation: [
          { season_index: 0, crop: "Corn", role: "cash_crop" },
          { season_index: 1, crop: "Soybeans", role: "cash_crop" },
        ],
        score_breakdown: breakdown([62, 55, 58, 60, 52, 80, 70]),
        summary: "The baseline. Strong yearly income, but the soil is bare after harvest and pests that follow these crops can build up.",
        benefits: ["Strong yearly income", "Familiar equipment and timing"],
        risks: ["Soil is bare between harvest and planting"],
        evidence: [{ statement: "Mapped crops for 2023 to 2025 are corn, soybeans and corn.", source: CSB }],
        information_gaps: ["Yields from past years are not included."],
      }),
    ],
    datasets_used: [POWER, SMAP, { ...SMAP, dataset: "SMAP L4 Soil Moisture" }, CSB, SSURGO, DEM],
    warnings: [
      "Soil moisture and weather values cover areas much larger than this field, so treat them as local context.",
      "Crop history before 2023 is missing, so older rotations were not considered.",
    ],
    disclaimer:
      "This tool supports your decisions. It does not replace a local agronomist or your county extension office, so check any change to your rotation with them first.",
  };
}
