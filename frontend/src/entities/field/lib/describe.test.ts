import type { FieldSelection } from "@/shared/api";
import { areaLine, boundaryNote, countyLine, fieldTitle } from "./describe";

const base: FieldSelection = {
  field_id: "fld_8a3f1c9e2b",
  anchor: { lat: 41.5868, lon: -93.625 },
  geometry: { type: "Polygon", coordinates: [] },
  resolved_by: "field_polygon",
  boundary_type: "estimated_csb",
  area_ha: 31.4,
  county: { fips: "19153", name: "Polk", state_postal: "IA" },
  source: "coordinates",
};

describe("field description", () => {
  it("titles a mapped field by id and a bare point plainly", () => {
    expect(fieldTitle(base)).toBe("Field fld_8a3f1c9e2b");
    expect(fieldTitle({ ...base, field_id: null })).toBe("Your point");
  });

  it("formats county and area in farm units", () => {
    expect(countyLine(base)).toBe("Polk County, IA");
    expect(areaLine(base)).toBe("About 78 acres");
    expect(areaLine({ ...base, area_ha: null })).toBeNull();
  });

  it("always says the outline is an estimate", () => {
    expect(boundaryNote(base)).toMatch(/^Estimated field area/);
  });

  it("explains snapping and buffered points", () => {
    expect(boundaryNote({ ...base, resolved_by: "snapped_point", snap_distance_m: 30 })).toMatch(/98 ft to the nearest field/);
    expect(
      boundaryNote({ ...base, field_id: null, resolved_by: "buffered_point", boundary_type: "buffered_point", buffer_m: 500 }),
    ).toBe("No mapped field here. We'll analyse a 500 m circle around your point.");
  });
});
