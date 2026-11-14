import { buildFieldSearch, parseFieldSearch } from "./field-url";

const parse = (qs: string) => parseFieldSearch(new URLSearchParams(qs));

describe("parseFieldSearch", () => {
  it("reads lat/lon into a point selection", () => {
    expect(parse("?lat=41.5868&lon=-93.625")).toEqual({
      ok: true,
      request: { ref: { point: { lat: 41.5868, lon: -93.625 } }, point: { lat: 41.5868, lon: -93.625 } },
    });
  });

  it("prefers field_id and keeps the point for display", () => {
    expect(parse("?field_id=fld_8a3f1c9e2b&lat=41.5&lon=-93.6")).toEqual({
      ok: true,
      request: { ref: { field_id: "fld_8a3f1c9e2b" }, point: { lat: 41.5, lon: -93.6 } },
    });
  });

  it("accepts field_id alone", () => {
    expect(parse("?field_id=fld_1")).toEqual({ ok: true, request: { ref: { field_id: "fld_1" }, point: null } });
  });

  it("reports missing location", () => {
    expect(parse("")).toEqual({ ok: false, problem: "missing" });
  });

  it("reports malformed or out-of-range coordinates", () => {
    expect(parse("?lat=abc&lon=-93")).toEqual({ ok: false, problem: "invalid" });
    expect(parse("?lat=95&lon=-93")).toEqual({ ok: false, problem: "invalid" });
    expect(parse("?lat=41")).toEqual({ ok: false, problem: "invalid" });
  });

  it("rejects field ids with unsafe characters", () => {
    expect(parse("?field_id=%3Cscript%3E")).toEqual({ ok: false, problem: "invalid" });
  });
});

describe("buildFieldSearch", () => {
  it("round-trips with parseFieldSearch", () => {
    const qs = buildFieldSearch({ fieldId: "fld_9", point: { lat: 41.58680012, lon: -93.625 } });
    expect(qs).toBe("?field_id=fld_9&lat=41.5868&lon=-93.625");
    const parsed = parse(qs);
    expect(parsed.ok && parsed.request.ref).toEqual({ field_id: "fld_9" });
  });
});
