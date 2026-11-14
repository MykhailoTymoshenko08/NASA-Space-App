import { describe, expect, it } from "vitest";
import { CROP_GROUPS, cropColorExpression, cropGroupOf } from "./crops";

describe("crop groups", () => {
  it("groups CDL class names", () => {
    expect(cropGroupOf("Corn").id).toBe("corn");
    expect(cropGroupOf("Soybeans").id).toBe("soy");
    expect(cropGroupOf("Winter Wheat").id).toBe("grain");
    expect(cropGroupOf("Alfalfa").id).toBe("hay");
    expect(cropGroupOf("Fallow/Idle Cropland").id).toBe("fallow");
    expect(cropGroupOf("Herbaceous Wetlands").id).toBe("noncrop");
  });

  it("puts unknown, empty and missing classes in other", () => {
    expect(cropGroupOf("Dbl Crop WinWht/Soybeans").id).toBe("other");
    expect(cropGroupOf("").id).toBe("other");
    expect(cropGroupOf(null).id).toBe("other");
  });

  it("lists each class name in one group only (a MapLibre match needs unique labels)", () => {
    const names = CROP_GROUPS.flatMap((g) => g.names);
    expect(new Set(names).size).toBe(names.length);
  });

  it("builds a match expression with the other color as fallback", () => {
    const expr = cropColorExpression((g) => g.id) as unknown[];
    expect(expr[0]).toBe("match");
    expect(expr[expr.length - 1]).toBe("other");
    expect(expr).toContainEqual(["Corn", "Sweet Corn", "Pop or Orn Corn"]);
  });
});
