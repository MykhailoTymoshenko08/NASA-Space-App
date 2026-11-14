import type { Metric } from "@/shared/api";
import { coarseWarning, groupSources, presentMetric } from "./present";

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

describe("presentMetric", () => {
  it("converts units and names the source", () => {
    const p = presentMetric(metric(), 31.4);
    expect(p).toMatchObject({ status: "ok", value: "27", unit: "% by volume", sourceName: "NASA SMAP L3 Enhanced Soil Moisture" });
    expect(p.status === "ok" && p.when).toBe("As of Nov 12, 2026");
  });

  it("does not double the provider when the dataset already names it", () => {
    const p = presentMetric(metric({ source: { dataset: "NASA POWER", provider: "NASA" } }), 31.4);
    expect(p.sourceName).toBe("NASA POWER");
  });

  it("labels estimates and modeled values with text, not color alone", () => {
    const est = presentMetric(metric({ quality: "estimated" }), 31.4);
    expect(est.status === "ok" && est.badge).toEqual({ tone: "info", text: "Estimate" });
    const mod = presentMetric(metric({ quality: "modeled" }), 31.4);
    expect(mod.status === "ok" && mod.badge).toEqual({ tone: "neutral", text: "Modeled" });
  });

  it("shows the reason for unavailable metrics, never a zero", () => {
    const p = presentMetric(metric({ value: null, quality: "unavailable", unavailable_reason: "No SMAP pass in 7 days" }), 31.4);
    expect(p).toEqual({ status: "unavailable", sourceName: "NASA SMAP L3 Enhanced Soil Moisture", reason: "No SMAP pass in 7 days" });
  });

  it("describes averaging periods", () => {
    const p = presentMetric(metric({ as_of: null, period: { start: "2026-11-05", end: "2026-11-12" } }), 31.4);
    expect(p.status === "ok" && p.when).toBe("Average, Nov 5 to Nov 12, 2026");
  });
});

describe("coarseWarning", () => {
  it("warns when the grid is much larger than the field", () => {
    // 31.4 ha field ≈ 560 m on a side; a 9 km cell is ~16x that.
    expect(coarseWarning(9000, 31.4)).toMatch(/regional average over about 5.6 mi/);
  });
  it("stays quiet for fine data or unknown sizes", () => {
    expect(coarseWarning(30, 31.4)).toBeNull();
    expect(coarseWarning(9000, null)).toBeNull();
    expect(coarseWarning(null, 31.4)).toBeNull();
  });
});

describe("groupSources", () => {
  it("groups by source and reports partial answers", () => {
    const rows = groupSources([
      metric({ key: "a", label: "Humidity", source: { dataset: "NASA POWER", provider: "NASA" } }),
      metric({ key: "b", label: "Temperature", source: { dataset: "NASA POWER", provider: "NASA" }, value: null, quality: "unavailable" }),
      metric({ key: "c", label: "Soil moisture" }),
    ]);
    expect(rows).toEqual([
      { name: "NASA POWER", url: null, measures: ["humidity", "temperature"], status: "partial" },
      { name: "NASA SMAP L3 Enhanced Soil Moisture", url: null, measures: ["soil moisture"], status: "done" },
    ]);
  });
});
