/**
 * Taps are less precise than a mouse: a finger that lands just off a small field, county or state still
 * means it. On a touch tap that misses the map's most specific layer, the tap is moved to the nearest
 * pixel within TAP_RADIUS_PX that hits it, and the whole hit is read there, so state, county, township
 * and field stay consistent (one real point, not a mix of nearby features).
 */

/** How far from the finger a tap may land and still count, in CSS px (about a fingertip). */
export const TAP_RADIUS_PX = 12;
const TAP_STEP_PX = 3;

export type Offset = { dx: number; dy: number };

/** Offsets inside a circle of `radius` on a `step` grid, nearest first, without the centre itself. */
export function tapOffsets(radius = TAP_RADIUS_PX, step = TAP_STEP_PX): Offset[] {
  const out: Offset[] = [];
  for (let dy = -radius; dy <= radius; dy += step) {
    for (let dx = -radius; dx <= radius; dx += step) {
      const d2 = dx * dx + dy * dy;
      if (d2 > 0 && d2 <= radius * radius) out.push({ dx, dy });
    }
  }
  return out.sort((a, b) => a.dx * a.dx + a.dy * a.dy - (b.dx * b.dx + b.dy * b.dy));
}

const TAP_OFFSETS = tapOffsets();

/** First offset (nearest first) where `hits` is true, or null when none within the radius. */
export function nearestHit(hits: (o: Offset) => boolean, offsets: readonly Offset[] = TAP_OFFSETS): Offset | null {
  for (const o of offsets) if (hits(o)) return o;
  return null;
}
