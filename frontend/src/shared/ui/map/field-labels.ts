import type { Feature, FeatureCollection, Point, Position } from "geojson";

const HA_TO_ACRES = 2.4710538;

type Ring = Position[];
type Piece = { polygon: Ring[]; area: number };

/** Shoelace area of a ring in degrees² (only used to compare pieces of one field). */
function ringArea(ring: Ring): number {
  let a = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    a += (ring[j]![0]! - ring[i]![0]!) * (ring[j]![1]! + ring[i]![1]!);
  }
  return Math.abs(a / 2);
}

function piecesOf(f: Feature): Piece[] {
  const g = f.geometry;
  const polys = g?.type === "Polygon" ? [g.coordinates] : g?.type === "MultiPolygon" ? g.coordinates : [];
  return polys.filter((p) => p[0] && p[0].length >= 4).map((p) => ({ polygon: p, area: ringArea(p[0]!) }));
}

/**
 * A point well inside a polygon: the midpoint of the longest horizontal run inside it, over a few
 * scan lines. Cheaper than polylabel and good enough for a label; a centroid can fall outside an
 * L- or U-shaped field.
 */
export function labelPoint(polygon: Ring[]): Position {
  const outer = polygon[0]!;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const [, y] of outer) {
    minY = Math.min(minY, y!);
    maxY = Math.max(maxY, y!);
  }
  let best: { len: number; at: Position } | null = null;
  const LINES = 7;
  for (let k = 1; k <= LINES; k++) {
    const y = minY + ((maxY - minY) * k) / (LINES + 1);
    const xs: number[] = [];
    for (const ring of polygon) {
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [x1, y1] = ring[j]! as [number, number];
        const [x2, y2] = ring[i]! as [number, number];
        if (y1 > y !== y2 > y) xs.push(x1 + ((y - y1) * (x2 - x1)) / (y2 - y1));
      }
    }
    xs.sort((a, b) => a - b);
    for (let i = 0; i + 1 < xs.length; i += 2) {
      const len = xs[i + 1]! - xs[i]!;
      if (!best || len > best.len) best = { len, at: [(xs[i]! + xs[i + 1]!) / 2, y] };
    }
  }
  return best?.at ?? outer[0]!;
}

/**
 * One label point per field from the loaded field tile features. Tiles split a field at tile edges,
 * so the same `field_id` arrives in pieces: the label goes in its largest piece.
 */
export function fieldLabelPoints(features: readonly Feature[]): FeatureCollection<Point> {
  const largest = new Map<string, { f: Feature; piece: Piece }>();
  for (const f of features) {
    const id = String(f.properties?.field_id ?? f.id ?? "");
    if (!id) continue;
    for (const piece of piecesOf(f)) {
      const cur = largest.get(id);
      if (!cur || piece.area > cur.piece.area) largest.set(id, { f, piece });
    }
  }
  const out: Feature<Point>[] = [];
  for (const [id, { f, piece }] of largest) {
    const area = f.properties?.area_ha;
    out.push({
      type: "Feature",
      id,
      properties: {
        field_id: id,
        crop_class: String(f.properties?.crop_class ?? ""),
        ...(typeof area === "number" ? { acres: Math.round(area * HA_TO_ACRES) } : {}),
      },
      geometry: { type: "Point", coordinates: labelPoint(piece.polygon) },
    });
  }
  return { type: "FeatureCollection", features: out };
}
