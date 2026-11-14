import { formatAcres, formatDistance, toDisplay } from "./units";

describe("toDisplay", () => {
  it("converts Celsius to Fahrenheit", () => {
    expect(toDisplay(0, "degC")).toEqual({ value: "32", unit: "°F" });
    expect(toDisplay(13.9, "degC")).toEqual({ value: "57", unit: "°F" });
  });

  it("converts mm to inches", () => {
    expect(toDisplay(25.4, "mm")).toEqual({ value: "1.0", unit: "in" });
    expect(toDisplay(910, "mm")).toEqual({ value: "35.8", unit: "in" });
  });

  it("keeps m3/m3 with two decimals", () => {
    expect(toDisplay(0.27, "m3/m3")).toEqual({ value: "0.27", unit: "m³/m³" });
  });

  it("shows fractions and percents", () => {
    expect(toDisplay(0.412, "fraction")).toEqual({ value: "0.41", unit: "" });
    expect(toDisplay(68, "%")).toEqual({ value: "68", unit: "%" });
    expect(toDisplay(3.84, "%")).toEqual({ value: "3.8", unit: "%" });
  });

  it("converts metres to feet", () => {
    expect(toDisplay(100, "m")).toEqual({ value: "328", unit: "ft" });
  });

  it("keeps g/kg and pH with their unit", () => {
    expect(toDisplay(1.84, "g/kg")).toEqual({ value: "1.8", unit: "g/kg" });
    expect(toDisplay(6.25, "pH")).toEqual({ value: "6.3", unit: "pH" });
  });

  it("passes class strings through without a unit", () => {
    expect(toDisplay("Silty clay loam", "class")).toEqual({ value: "Silty clay loam", unit: "" });
  });

  it("shows unknown units as-is instead of dropping them", () => {
    expect(toDisplay(3.14159, "W/m2")).toEqual({ value: "3.14", unit: "W/m2" });
  });
});

describe("formatAcres", () => {
  it("rounds large areas to whole acres", () => {
    expect(formatAcres(31.4)).toBe("78");
    expect(formatAcres(64.75)).toBe("160");
  });
  it("keeps one decimal for small areas", () => {
    expect(formatAcres(2)).toBe("4.9");
  });
});

describe("formatDistance", () => {
  it("uses miles for long distances and feet for short ones", () => {
    expect(formatDistance(9000)).toBe("5.6 mi");
    expect(formatDistance(30)).toBe("98 ft");
  });
});
