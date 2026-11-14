import type { SelectionRef } from "@/shared/api";
import { isValidLatLon, parseCoordinate, type LatLon } from "@/shared/lib";

/**
 * The selected field lives in the URL (?field_id=… and/or ?lat=…&lon=…), never only in memory,
 * so refresh and share work. field_id wins when present (the contract prefers it).
 */
export type FieldRequest = { ref: SelectionRef; point: LatLon | null };
export type FieldUrlProblem = "missing" | "invalid";
export type ParsedFieldUrl = { ok: true; request: FieldRequest } | { ok: false; problem: FieldUrlProblem };

const FIELD_ID_RE = /^[A-Za-z0-9_-]{1,128}$/;

export function parseFieldSearch(params: URLSearchParams): ParsedFieldUrl {
  const fieldId = params.get("field_id")?.trim() || null;
  const lat = parseCoordinate(params.get("lat"));
  const lon = parseCoordinate(params.get("lon"));
  const hasLatLon = params.has("lat") || params.has("lon");

  let point: LatLon | null = null;
  if (lat !== null && lon !== null && isValidLatLon({ lat, lon })) point = { lat, lon };

  if (fieldId) {
    if (!FIELD_ID_RE.test(fieldId)) return { ok: false, problem: "invalid" };
    return { ok: true, request: { ref: { field_id: fieldId }, point } };
  }
  if (point) return { ok: true, request: { ref: { point }, point } };
  return { ok: false, problem: hasLatLon ? "invalid" : "missing" };
}

/** Build the /field query string. Coordinates are rounded to 6 decimals (~10 cm). */
export function buildFieldSearch(input: { fieldId?: string | null; point?: LatLon | null }): string {
  const params = new URLSearchParams();
  if (input.fieldId) params.set("field_id", input.fieldId);
  if (input.point) {
    params.set("lat", input.point.lat.toFixed(6).replace(/\.?0+$/, ""));
    params.set("lon", input.point.lon.toFixed(6).replace(/\.?0+$/, ""));
  }
  return `?${params.toString()}`;
}
