import type { FieldSelection } from "@/shared/api";
import {
  areaText,
  boundaryNote,
  countyLine,
  cropHistoryLabels,
  fieldKind,
  selectionKey,
  selectionRef,
  selectionSearch,
} from "./describe";

const base: FieldSelection = {
  field_id: "csb2025_190000123456",
  anchor: { lat: 41.5868, lon: -93.625 },
  geometry: { type: "Polygon", coordinates: [] },
  resolved_by: "field_polygon",
  boundary_type: "estimated_csb",
  area_ha: 32.4,
  crop_history: [
    { year: 2025, crop: "Corn" },
    { year: 2024, crop: "Soybeans" },
  ],
  county: { fips: "19153", name: "Polk", state_postal: "IA" },
  source: "coordinates",
};
const buffered: FieldSelection = {
  ...base,
  field_id: null,
  resolved_by: "buffered_point",
  boundary_type: "buffered_point",
  buffer_m: 300,
  crop_history: [],
};

describe("field description", () => {
  it("names the kind of area honestly", () => {
    expect(fieldKind(base)).toBe("Estimated field area");
    expect(fieldKind(buffered)).toBe("Circle around your point");
  });

  it("formats county and area in acres and hectares", () => {
    expect(countyLine(base)).toBe("Polk County, IA");
    expect(areaText(base)).toBe("80 acres (32.4 ha)");
    expect(areaText({ ...base, area_ha: null })).toBeNull();
  });

  it("never implies a legal boundary", () => {
    expect(boundaryNote(base)).toMatch(/not a legal or ownership boundary/);
    expect(boundaryNote({ ...base, resolved_by: "snapped_point", snap_distance_m: 120 })).toMatch(
      /snapped from your point to the nearest outline, 120 m \(394 ft\) away/,
    );
    expect(boundaryNote(buffered)).toBe(
      "No field outline here, so we use a circle of 300 m (984 ft) around your point. Values are for that circle.",
    );
  });

  it("lists mapped crops newest first", () => {
    expect(cropHistoryLabels(base)).toEqual(["2025 Corn", "2024 Soybeans"]);
  });

  it("refers back to the field by id, or by point when there is none", () => {
    expect(selectionRef(base)).toEqual({ field_id: "csb2025_190000123456" });
    expect(selectionRef(buffered)).toEqual({ point: { lat: 41.5868, lon: -93.625 } });
    expect(selectionSearch(base)).toBe("?field_id=csb2025_190000123456&lat=41.5868&lon=-93.625");
    expect(selectionKey(buffered)).toBe("pt:41.58680,-93.62500");
  });
});
