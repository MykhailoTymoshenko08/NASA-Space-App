import { describe, expect, it } from "vitest";
import { nearestHit, TAP_RADIUS_PX, tapOffsets } from "./touch-hit";

const dist = (o: { dx: number; dy: number }) => Math.hypot(o.dx, o.dy);

describe("tapOffsets", () => {
  it("covers the circle around the tap, nearest first, without the tap itself", () => {
    const offsets = tapOffsets();
    expect(offsets.length).toBeGreaterThan(20);
    expect(offsets.some((o) => o.dx === 0 && o.dy === 0)).toBe(false);
    expect(offsets.every((o) => dist(o) <= TAP_RADIUS_PX)).toBe(true);
    for (let i = 1; i < offsets.length; i++) expect(dist(offsets[i]!)).toBeGreaterThanOrEqual(dist(offsets[i - 1]!));
  });
});

describe("nearestHit", () => {
  it("returns the nearest offset that hits", () => {
    // A field whose edge is 7 px to the right of the tap.
    expect(nearestHit((o) => o.dx >= 7)).toEqual({ dx: 9, dy: 0 });
  });

  it("returns null when nothing is within reach", () => {
    expect(nearestHit((o) => o.dx > TAP_RADIUS_PX)).toBeNull();
  });
});
