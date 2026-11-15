import { describe, expect, it } from "vitest";
import { parseCropBudgets, type CropBudgetDraft } from "./CropBudgetInputs";

const row = (over: Partial<CropBudgetDraft> = {}): CropBudgetDraft => ({
  crop: "corn", low: "700", base: "850", high: "1000", production: "520", ...over,
});

describe("parseCropBudgets", () => {
  it("returns no overrides for no rows", () => {
    expect(parseCropBudgets([])).toEqual({ overrides: [], error: null });
  });

  it("parses complete rows, keeping an explicit zero", () => {
    expect(parseCropBudgets([row(), row({ crop: "oats", low: "0", base: "0", high: "0", production: "0" })])).toEqual({
      overrides: [
        { crop: "corn", revenue_per_acre: { low: 700, base: 850, high: 1000 }, production_cost_per_acre: 520 },
        { crop: "oats", revenue_per_acre: { low: 0, base: 0, high: 0 }, production_cost_per_acre: 0 },
      ],
      error: null,
    });
  });

  it("rejects blanks instead of treating them as zero", () => {
    expect(parseCropBudgets([row({ production: " " })]).error).toMatch(/enter all revenue/);
  });

  it("rejects duplicate crops, unknown crops and out-of-order revenue", () => {
    expect(parseCropBudgets([row(), row()]).error).toMatch(/only one budget for corn/);
    expect(parseCropBudgets([row({ crop: "rice" })]).error).toMatch(/Choose a crop/);
    expect(parseCropBudgets([row({ low: "900", base: "850" })]).error).toMatch(/lower prices ≤ base/);
  });

  it("rejects out-of-range figures", () => {
    expect(parseCropBudgets([row({ high: "100001" })]).error).toMatch(/gross revenue/);
    expect(parseCropBudgets([row({ production: "-1" })]).error).toMatch(/production cost/);
    expect(parseCropBudgets([row({ base: "abc" })]).error).toMatch(/gross revenue/);
  });
});
