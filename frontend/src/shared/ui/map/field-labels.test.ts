import type { Feature } from "geojson";
import { describe, expect, it } from "vitest";
import { fieldLabelPoints, labelPoint } from "./field-labels";

const square = (x0: number, y0: number, x1: number, y1: number) => [
  [
    [x0, y0],
    [x1, y0],
    [x1, y1],
    [x0, y1],
    [x0, y0],
  ],
];
const piece = (id: string, coords: number[][][], props: Record<string, unknown> = {}): Feature => ({
  type: "Feature",
  id,
  properties: { field_id: id, crop_class: "Corn", area_ha: 32.45, ...props },
  geometry: { type: "Polygon", coordinates: coords },
});

describe("fieldLabelPoints", () => {
  it("gives a field split across tiles one label, in its largest piece", () => {
    const out = fieldLabelPoints([piece("a", square(0, 0, 1, 1)), piece("a", square(1, 0, 4, 1)), piece("b", square(5, 5, 6, 6))]);
    expect(out.features).toHaveLength(2);
    const [x] = out.features.find((f) => f.id === "a")!.geometry.coordinates;
    expect(x).toBeGreaterThan(1);
  });

  it("rounds acres and keeps an empty crop", () => {
    const [f] = fieldLabelPoints([piece("a", square(0, 0, 1, 1), { crop_class: "" })]).features;
    expect(f!.properties).toEqual({ field_id: "a", crop_class: "", acres: 80 });
  });

  it("omits acres when the area is unknown", () => {
    const [f] = fieldLabelPoints([piece("a", square(0, 0, 1, 1), { area_ha: null })]).features;
    expect(f!.properties).not.toHaveProperty("acres");
  });
});

describe("labelPoint", () => {
  it("lands inside a U-shaped field, where the centroid would not", () => {
    // U: two 1-wide arms joined at the bottom; the centroid (1.5, ~1.2) lies in the gap.
    const u = [
      [
        [0, 0],
        [3, 0],
        [3, 3],
        [2, 3],
        [2, 1],
        [1, 1],
        [1, 3],
        [0, 3],
        [0, 0],
      ],
    ];
    const [x, y] = labelPoint(u) as [number, number];
    const inGap = x > 1 && x < 2 && y > 1;
    expect(inGap).toBe(false);
  });
});
