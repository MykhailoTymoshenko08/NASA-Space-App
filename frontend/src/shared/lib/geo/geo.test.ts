import {
  bboxOfRing,
  formatLatLon,
  fromPosition,
  isValidLatLon,
  parseCoordinate,
  projectToBox,
  toPosition,
} from "./geo";

describe("position conversion", () => {
  it("puts longitude first for GeoJSON and back", () => {
    expect(toPosition({ lat: 41.5868, lon: -93.625 })).toEqual([-93.625, 41.5868]);
    expect(fromPosition([-93.625, 41.5868])).toEqual({ lat: 41.5868, lon: -93.625 });
  });
});

describe("formatLatLon", () => {
  it("uses hemisphere letters instead of signs", () => {
    expect(formatLatLon({ lat: 42.0347, lon: -93.462 })).toBe("42.0347° N, 93.4620° W");
    expect(formatLatLon({ lat: -33.9, lon: 18.4 }, 1)).toBe("33.9° S, 18.4° E");
  });
});

describe("isValidLatLon", () => {
  it("rejects out-of-range and non-finite values", () => {
    expect(isValidLatLon({ lat: 41, lon: -93 })).toBe(true);
    expect(isValidLatLon({ lat: 91, lon: 0 })).toBe(false);
    expect(isValidLatLon({ lat: 0, lon: -181 })).toBe(false);
    expect(isValidLatLon({ lat: NaN, lon: 0 })).toBe(false);
  });
});

describe("parseCoordinate", () => {
  it("parses decimal strings and rejects junk", () => {
    expect(parseCoordinate("41.5868")).toBe(41.5868);
    expect(parseCoordinate("-93.625")).toBe(-93.625);
    expect(parseCoordinate("")).toBeNull();
    expect(parseCoordinate(null)).toBeNull();
    expect(parseCoordinate("abc")).toBeNull();
  });
});

describe("bboxOfRing", () => {
  it("returns [west, south, east, north]", () => {
    const ring = [[-93.626, 41.586], [-93.624, 41.586], [-93.624, 41.588], [-93.626, 41.588], [-93.626, 41.586]];
    expect(bboxOfRing(ring)).toEqual([-93.626, 41.586, -93.624, 41.588]);
  });
});

describe("projectToBox", () => {
  it("keeps north at the top and fits inside the padded box", () => {
    const ring = [[-93.626, 41.586], [-93.624, 41.586], [-93.624, 41.588], [-93.626, 41.588], [-93.626, 41.586]];
    const out = projectToBox([ring], 320, 200, 20, { lat: 41.588, lon: -93.625 });
    expect(out.paths).toHaveLength(1);
    expect(out.point!.y).toBeCloseTo(20, 5); // northern edge = top padding
    const nums = out.paths[0]!.match(/-?\d+(\.\d+)?/g)!.map(Number);
    for (const v of nums) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(320);
    }
  });

  it("returns nothing for an empty polygon", () => {
    expect(projectToBox([], 100, 100, 0)).toEqual({ paths: [], point: null });
  });
});
