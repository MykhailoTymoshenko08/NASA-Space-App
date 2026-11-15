import { buildAnalysisRequest, initialCropRows } from "./setup";

const mapped = [
  { year: 2025, crop: "Corn" },
  { year: 2024, crop: "Soybeans" },
];

describe("analysis setup", () => {
  it("leaves crop history out when the farmer did not change it", () => {
    const req = buildAnalysisRequest({
      selection: { field_id: "csb2025_1" },
      priorities: ["soil_health"],
      crops: mapped,
      mapped,
      horizon: 3,
    });
    expect(req).toEqual({
      selection: { field_id: "csb2025_1" },
      options: { priorities: ["soil_health"], horizon_years: 3 },
    });
  });

  it("sends the corrected history, trimmed and without empty years", () => {
    const req = buildAnalysisRequest({
      selection: { field_id: "csb2025_1" },
      priorities: [],
      crops: [
        { year: 2025, crop: " Wheat " },
        { year: 2024, crop: "" },
      ],
      mapped,
      horizon: 5,
    });
    expect(req.options?.crop_history).toEqual([{ year: 2025, crop: "Wheat" }]);
  });

  it("offers the last three years empty when nothing is mapped", () => {
    expect(initialCropRows(null, new Date("2026-11-14T00:00:00Z"))).toEqual([
      { year: 2025, crop: "" },
      { year: 2024, crop: "" },
      { year: 2023, crop: "" },
    ]);
  });

  it("preserves an explicit zero land cost and local cover cost", () => {
    const req = buildAnalysisRequest({ selection: { field_id: "csb2025_1" }, priorities: [],
      crops: mapped, mapped, horizon: 3,
      budget: { land_rent_per_acre: 0, cover_cost_per_acre: 35 } });
    expect(req.options?.budget).toEqual({ land_rent_per_acre: 0, cover_cost_per_acre: 35 });
  });
});
