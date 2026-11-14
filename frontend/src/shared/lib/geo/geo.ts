/**
 * All coordinate conversions live here (the classic [lon, lat] vs {lat, lon} bug).
 * - Our API objects: { lat, lon } (WGS84).
 * - GeoJSON positions: [lon, lat]. BBox: [west, south, east, north].
 */

export type LatLon = { lat: number; lon: number };
export type Position = [lon: number, lat: number];
export type BBox = [west: number, south: number, east: number, north: number];

export const isValidLatLon = (p: LatLon) =>
  Number.isFinite(p.lat) && Number.isFinite(p.lon) && Math.abs(p.lat) <= 90 && Math.abs(p.lon) <= 180;

export const toPosition = (p: LatLon): Position => [p.lon, p.lat];
export const fromPosition = (pos: readonly number[]): LatLon => ({ lat: pos[1] ?? NaN, lon: pos[0] ?? NaN });

/** "42.0347° N, 93.4620° W" (design format). */
export function formatLatLon(p: LatLon, decimals = 4): string {
  const ns = p.lat >= 0 ? "N" : "S";
  const ew = p.lon >= 0 ? "E" : "W";
  return `${Math.abs(p.lat).toFixed(decimals)}° ${ns}, ${Math.abs(p.lon).toFixed(decimals)}° ${ew}`;
}

/** Parse a decimal-degree number from a URL param. Returns null if missing or malformed. */
export function parseCoordinate(raw: string | null): number | null {
  if (raw === null || raw.trim() === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

export function bboxOfRing(ring: readonly (readonly number[])[]): BBox {
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  for (const pos of ring) {
    const { lat, lon } = fromPosition(pos);
    if (lon < w) w = lon;
    if (lon > e) e = lon;
    if (lat < s) s = lat;
    if (lat > n) n = lat;
  }
  return [w, s, e, n];
}

export type ProjectedSketch = {
  /** SVG path for each ring, in viewBox units. */
  paths: string[];
  /** Projected point, or null if none was given. */
  point: { x: number; y: number } | null;
};

/**
 * Project polygon rings (+ optional point) into a width x height box with padding,
 * using a local equirectangular projection (fine at field scale).
 */
export function projectToBox(
  rings: readonly (readonly (readonly number[])[])[],
  width: number,
  height: number,
  padding: number,
  point?: LatLon,
): ProjectedSketch {
  const outer = rings[0] ?? [];
  if (outer.length === 0) return { paths: [], point: null };
  const [w, s, e, n] = bboxOfRing(outer);
  const midLat = ((s + n) / 2) * (Math.PI / 180);
  const kx = Math.cos(midLat); // shrink longitude degrees toward the poles
  const spanX = Math.max((e - w) * kx, 1e-9);
  const spanY = Math.max(n - s, 1e-9);
  const scale = Math.min((width - 2 * padding) / spanX, (height - 2 * padding) / spanY);
  const offX = (width - spanX * scale) / 2;
  const offY = (height - spanY * scale) / 2;

  const project = (p: LatLon) => ({
    x: offX + (p.lon - w) * kx * scale,
    y: offY + (n - p.lat) * scale,
  });

  const paths = rings.map((ring) =>
    ring
      .map((pos, i) => {
        const { x, y } = project(fromPosition(pos));
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join("") + "Z",
  );
  return { paths, point: point ? project(point) : null };
}
