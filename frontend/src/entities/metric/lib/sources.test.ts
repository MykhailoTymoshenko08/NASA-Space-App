import type { Metric } from "@/shared/api";
import { readingFor } from "./glossary";
import { buildSourceRegistry } from "./sources";

const metric = (over: Partial<Metric>): Metric => ({
  key: "k",
  label: "Label",
  category: "moisture",
  value: 1,
  unit: "none",
  as_of: null,
  period: null,
  quality: "measured",
  unavailable_reason: null,
  source: { dataset: "SMAP L3 Enhanced Soil Moisture", provider: "NASA", url: null },
  resolution_m: 9000,
  note: null,
  ...over,
});

describe("buildSourceRegistry", () => {
  it("numbers datasets by first appearance in group order and dedupes them", () => {
    const reg = buildSourceRegistry([
      metric({ key: "ph", label: "Soil pH", category: "soil", source: { dataset: "gSSURGO soil survey", provider: "USDA NRCS", url: "https://www.nrcs.usda.gov/x" }, resolution_m: 30 }),
      metric({ key: "sm", label: "Soil moisture (surface)" }),
      metric({ key: "som", label: "Soil organic matter", category: "soil", source: { dataset: "gSSURGO soil survey", provider: "USDA NRCS", url: null }, resolution_m: 30 }),
    ]);
    expect(reg.list.map((e) => [e.n, e.short])).toEqual([
      [1, "SMAP L3"],
      [2, "gSSURGO"],
    ]);
    expect(reg.forMetric("som")?.n).toBe(2);
    expect(reg.list[1]!.usedFor).toEqual(["Soil pH", "Soil organic matter"]);
    expect(reg.list[1]!.host).toBe("nrcs.usda.gov");
    expect(reg.list[1]!.detail[0]).toMatch(/^Pixel about/);
    expect(reg.providersLine).toBe("NASA and USDA NRCS");
  });

  it("appends extra datasets no metric cites, and keeps unknown names", () => {
    const reg = buildSourceRegistry([metric({})], [
      { dataset: "SMAP L3 Enhanced Soil Moisture", provider: "NASA" },
      { dataset: "Some new dataset (beta), v2", provider: "Other", coverage_period: "2018-2025" },
    ]);
    expect(reg.list).toHaveLength(2);
    expect(reg.list[1]!.short).toBe("Some new dataset");
    expect(reg.list[1]!.what).toBe("");
    expect(reg.list[1]!.usedFor).toEqual([]);
    expect(reg.list[1]!.detail).toContain("2018-2025");
    expect(reg.providersLine).toBe("NASA and Other");
  });
});

describe("readingFor", () => {
  it("reads NDVI and the moisture anomaly in plain words", () => {
    expect(readingFor(metric({ key: "vegetation_index_ndvi", value: 0.31 }), [])).toBe(
      "Light cover, such as stubble or a young cover crop.",
    );
    expect(readingFor(metric({ key: "soil_moisture_anomaly", value: -0.7 }), [])).toBe("A bit drier than normal.");
    expect(readingFor(metric({ key: "vegetation_index_ndvi", value: null }), [])).toBe("");
  });

  it("compares ET with 30-day rain", () => {
    const et = metric({ key: "et_30d_total", value: 38, unit: "mm" });
    const rain = metric({ key: "precip_30d_total", value: 41, unit: "mm" });
    expect(readingFor(et, [et, rain])).toBe(
      "Rain over the same 30 days was 1.6 in, about the same as the 1.5 in the field gave back.",
    );
    expect(readingFor(et, [et])).toBe("");
  });
});
