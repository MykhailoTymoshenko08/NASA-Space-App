import type { Metric } from "@/shared/api";
import { groupMetrics, presentMetric } from "./present";

const metric = (over: Partial<Metric> = {}): Metric => ({
  key: "soil_moisture_surface",
  label: "Soil moisture (surface)",
  category: "moisture",
  value: 0.27,
  unit: "m3/m3",
  as_of: "2026-11-12",
  period: null,
  quality: "measured",
  unavailable_reason: null,
  source: { dataset: "SMAP L3 Enhanced Soil Moisture", provider: "NASA", url: null },
  resolution_m: 9000,
  note: null,
  ...over,
});

const FIELD_M = Math.sqrt(32.4 * 10_000); // about 570 m

describe("presentMetric", () => {
  it("shows value, unit, quality, date, source and pixel size", () => {
    expect(presentMetric(metric(), FIELD_M)).toMatchObject({
      available: true,
      value: "0.27",
      unit: "m³/m³",
      quality: { label: "Measured", tone: "success" },
      when: "As of Nov 12, 2026",
      source: "SMAP L3 Enhanced Soil Moisture, NASA",
      pixel: "Pixel about 5.6 mi",
      coarse: true,
    });
  });

  it("labels estimates and long-term values", () => {
    const p = presentMetric(metric({ quality: "estimated", as_of: null, resolution_m: 30, unit: "g/kg", value: 1.9 }), FIELD_M);
    expect(p.quality.label).toBe("Estimate");
    expect(p.when).toBe("Long-term value");
    expect(p.coarse).toBe(false);
  });

  it("shows Not available with the reason, never a made-up value", () => {
    const p = presentMetric(metric({ value: null, quality: "unavailable", unavailable_reason: "No pass." }), FIELD_M);
    expect(p).toMatchObject({ available: false, value: "Not available", unit: "", note: "No pass.", coarse: false });
  });
});

describe("groupMetrics", () => {
  it("groups by category in design order and keeps unknown categories", () => {
    const groups = groupMetrics([
      metric({ key: "a", category: "soil" }),
      metric({ key: "b", category: "moisture" }),
      metric({ key: "c", category: "something_new" as Metric["category"] }),
    ]);
    expect(groups.map((g) => g.title)).toEqual(["Moisture", "Soil", "Other"]);
  });
});
