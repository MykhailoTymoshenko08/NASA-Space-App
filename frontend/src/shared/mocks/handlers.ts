/**
 * MSW handlers typed from the generated contract types, so contract drift breaks the build.
 * Demo data only. Scenarios are picked by the requested point:
 *  - default (Corn Belt)         : mapped field, all metrics answered
 *  - lat >= 45                   : soil moisture unavailable (shows a card's error state)
 *  - lon > -90 (east)            : no mapped field, buffered 500 m circle
 *  - outside the contiguous US   : 422 OUTSIDE_COVERAGE
 *  - field_id "fld_missing"      : 404 NOT_FOUND
 */
import { delay, http, HttpResponse, type AnyHandler } from "msw";
import type { components } from "@/shared/api";
import { env } from "@/shared/config";

type S = components["schemas"];
type LatLon = S["LatLon"];

const url = (path: string) => `${env.apiBaseUrl}${path}`;
const wait = () => delay(import.meta.env.MODE === "test" ? 0 : 900);
const requestId = () => `mock-${Math.random().toString(36).slice(2, 10)}`;

const CONUS = { west: -125, south: 24.5, east: -66.9, north: 49.5 };
const inConus = (p: LatLon) => p.lon >= CONUS.west && p.lon <= CONUS.east && p.lat >= CONUS.south && p.lat <= CONUS.north;

const DEFAULT_POINT: LatLon = { lat: 41.5868, lon: -93.625 };

function errorResponse(status: number, code: S["ErrorCode"], message: string) {
  const id = requestId();
  return HttpResponse.json<S["ErrorResponse"]>(
    { error: { code, message, request_id: id } },
    { status, headers: { "X-Request-Id": id } },
  );
}

/** A slightly skewed ~560 m square around the point (about 78 acres). */
function fieldPolygon(c: LatLon): S["GeoJSONPolygon"] {
  const dLat = 0.0025;
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

function selectionFor(p: LatLon, fieldId: string | null): S["FieldSelection"] {
  const buffered = fieldId === null && p.lon > -90;
  const county = { fips: "19153", name: "Polk", state_postal: "IA" };
  if (buffered) {
    return {
      field_id: null,
      anchor: p,
      geometry: circlePolygon(p, 500),
      resolved_by: "buffered_point",
      boundary_type: "buffered_point",
      snap_distance_m: null,
      buffer_m: 500,
      area_ha: 78.5,
      crop_class: null,
      crop_history: [],
      county,
      source: "coordinates",
    };
  }
  return {
    field_id: fieldId ?? `fld_demo${Math.abs(Math.round(p.lat * 1000 + p.lon * 1000)) % 100000}`,
    anchor: p,
    geometry: fieldPolygon(p),
    resolved_by: fieldId ? "field_polygon" : "snapped_point",
    boundary_type: "estimated_csb",
    snap_distance_m: fieldId ? 0 : 42,
    buffer_m: null,
    area_ha: 31.4,
    crop_class: "Corn",
    crop_history: [
      { year: 2025, crop: "Corn" },
      { year: 2024, crop: "Soybeans" },
    ],
    county,
    source: "coordinates",
  };
}

function metricsFor(p: LatLon): S["Metric"][] {
  const smapDown = p.lat >= 45;
  const period = { start: "2026-11-06", end: "2026-11-12" };
  const power = { dataset: "NASA POWER", provider: "NASA", url: "https://power.larc.nasa.gov/" };
  return [
    {
      key: "relative_humidity_2m",
      label: "Relative humidity",
      category: "atmosphere",
      value: 68,
      unit: "%",
      as_of: "2026-11-12",
      period,
      quality: "modeled",
      unavailable_reason: null,
      source: power,
      resolution_m: 55_000,
      note: "Average of the last 7 days.",
    },
    smapDown
      ? {
          key: "soil_moisture_surface",
          label: "Soil moisture (surface)",
          category: "moisture",
          value: null,
          unit: "m3/m3",
          as_of: null,
          period: null,
          quality: "unavailable",
          unavailable_reason: "No satellite pass over this spot in the last 7 days.",
          source: { dataset: "SMAP L3 Enhanced Soil Moisture", provider: "NASA", url: null },
          resolution_m: 9000,
          note: null,
        }
      : {
          key: "soil_moisture_surface",
          label: "Soil moisture (surface)",
          category: "moisture",
          value: 0.27,
          unit: "m3/m3",
          as_of: "2026-11-12",
          period,
          quality: "measured",
          unavailable_reason: null,
          source: { dataset: "SMAP L3 Enhanced Soil Moisture", provider: "NASA", url: null },
          resolution_m: 9000,
          note: "Top 5 cm of soil.",
        },
    {
      key: "air_temp_mean_2m",
      label: "Air temperature (mean)",
      category: "temperature",
      value: 13.9,
      unit: "degC",
      as_of: "2026-11-12",
      period,
      quality: "modeled",
      unavailable_reason: null,
      source: power,
      resolution_m: 55_000,
      note: "Daily average of the last 7 days.",
    },
    {
      key: "soil_nitrogen_total",
      label: "Soil nitrogen (total)",
      category: "soil",
      value: 1.8,
      unit: "g/kg",
      as_of: null,
      period: null,
      quality: "estimated",
      unavailable_reason: null,
      source: { dataset: "Demo nitrogen estimate", provider: "Mock", url: null },
      resolution_m: 250,
      note: "Estimated, not a lab test.",
    },
    {
      key: "precip_30d_total",
      label: "Rain, last 30 days",
      category: "precipitation",
      value: 52,
      unit: "mm",
      as_of: "2026-11-12",
      period: { start: "2026-10-14", end: "2026-11-12" },
      quality: "modeled",
      unavailable_reason: null,
      source: power,
      resolution_m: 55_000,
      note: null,
    },
  ];
}

export const handlers: AnyHandler[] = [
  http.get(url("/health"), () => HttpResponse.json({ status: "ok" as const })),

  http.post<never, { selection: S["SelectionRef"] }, S["Snapshot"] | S["ErrorResponse"]>(url("/snapshots"), async ({ request }) => {
    await wait();
    const ref = (await request.json()).selection;
    let point: LatLon;
    let fieldId: string | null = null;
    if ("field_id" in ref) {
      if (ref.field_id === "fld_missing") return errorResponse(404, "NOT_FOUND", "No field with that id.");
      fieldId = ref.field_id;
      point = DEFAULT_POINT;
    } else {
      point = ref.point;
    }
    if (!inConus(point)) return errorResponse(422, "OUTSIDE_COVERAGE", "Point is outside CONUS.");

    return HttpResponse.json<S["Snapshot"]>({
      selection: selectionFor(point, fieldId),
      generated_at: new Date().toISOString(),
      cached: false,
      metrics: metricsFor(point),
    });
  }),

  http.post(url("/analyses"), async () => {
    await wait();
    return HttpResponse.json<S["AnalysisJob"]>(
      {
        job_id: crypto.randomUUID(),
        status: "queued",
        created_at: new Date().toISOString(),
        finished_at: null,
        progress: { percent: 0, stage: "Queued" },
      },
      { status: 202 },
    );
  }),
];
