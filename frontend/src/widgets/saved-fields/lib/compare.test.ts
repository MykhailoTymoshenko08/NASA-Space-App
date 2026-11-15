import type { ComparisonRow } from "@/entities/comparison";
import { barPercents, compareValue, planText, sharedCellNote, usd } from "./compare";

const row = (better: ComparisonRow["better"], values: (number | null)[], unit = "index"): ComparisonRow => ({
  key: "k",
  label: "K",
  group: "soil",
  unit,
  better,
  best: [],
  same_for_all: false,
  cells: values.map((v, i) => ({ saved_field_id: String(i), value: v, quality: v === null ? "unavailable" : "measured" })),
});

describe("usd", () => {
  it("writes losses with a true minus and drops minus zero", () => {
    expect(usd(1234.4)).toBe("$1,234");
    expect(usd(-45)).toBe("−$45");
    expect(usd(-0.2)).toBe("$0");
    expect(usd(3.456, 2)).toBe("$3.46");
  });
});

describe("compareValue", () => {
  it("formats comparison units in US terms", () => {
    expect(compareValue(265, "USD/acre/year")).toEqual({ value: "$265", unit: "per acre a year" });
    expect(compareValue(-8600, "USD/year")).toEqual({ value: "−$8,600", unit: "a year" });
    expect(compareValue(3.4, "USD/acre/point")).toEqual({ value: "$3.40", unit: "per acre per point" });
    expect(compareValue(1, "years")).toEqual({ value: "1", unit: "year" });
    expect(compareValue(10, "km")).toEqual({ value: "6.2", unit: "mi" });
    expect(compareValue(32.4, "ha")).toEqual({ value: "80", unit: "acres" });
    expect(compareValue(910, "mm")).toEqual({ value: "35.8", unit: "in" });
    expect(compareValue("Loam", "class")).toEqual({ value: "Loam", unit: "" });
  });
});

describe("barPercents", () => {
  it("scales higher-is-better rows to the largest value", () => {
    const r = row("higher", [80, 40, null]);
    expect(barPercents(r, r.cells)).toEqual([100, 50, null]);
  });
  it("draws no bars where they would mislead", () => {
    for (const r of [row("lower", [1, 2]), row("target", [6, 7]), row("higher", [-5, 10]), row("higher", [5, null])]) {
      expect(barPercents(r, r.cells)).toBeNull();
    }
  });
});

describe("sharedCellNote", () => {
  it("folds a note every available cell shares, never a missing-value reason", () => {
    const r = row("higher", [3, 4]);
    r.cells.forEach((c) => (c.note = "Survey 2024."));
    expect(sharedCellNote(r)).toBe("Survey 2024.");
    const missing = row("higher", [null, null]);
    missing.cells.forEach((c) => (c.note = "Soil source is down."));
    expect(sharedCellNote(missing)).toBeNull();
  });
});

describe("planText", () => {
  it("reads the plan as a sentence", () => {
    expect(planText({ rotation: ["corn", "soybean"], horizon_years: 2 })).toBe("Corn, then soybeans, over 2 years");
    expect(planText({ rotation: ["corn"], horizon_years: 2 })).toBe("Corn every year, over 2 years");
  });
});
