import { describe, expect, it } from "vitest";
import { offsetFromCenter, shouldCenter } from "./center-on-approach";

describe("offsetFromCenter", () => {
  it("is zero for an element centered in the window", () => {
    expect(offsetFromCenter({ top: 24, height: 852 }, 900)).toBe(0);
  });
  it("is positive below the middle, negative above", () => {
    expect(offsetFromCenter({ top: 100, height: 852 }, 900)).toBe(76);
    expect(offsetFromCenter({ top: -100, height: 852 }, 900)).toBe(-124);
  });
});

describe("shouldCenter", () => {
  const reach = 450;

  it("centers after scrolling down toward the element and stopping near it", () => {
    expect(shouldCenter(900, 300, reach)).toBe(true);
  });
  it("centers after scrolling up toward the element from below", () => {
    expect(shouldCenter(-900, -200, reach)).toBe(true);
  });
  it("leaves a scroll away from the element alone, so the page scrolls on past it", () => {
    expect(shouldCenter(0, -100, reach)).toBe(false);
    expect(shouldCenter(-100, -300, reach)).toBe(false);
  });
  it("leaves a scroll that ran past the middle alone", () => {
    expect(shouldCenter(400, -100, reach)).toBe(false);
  });
  it("leaves a scroll that stopped far from the element alone", () => {
    expect(shouldCenter(1500, 800, reach)).toBe(false);
  });
  it("does nothing once the element is centered", () => {
    expect(shouldCenter(300, 1, reach)).toBe(false);
  });
});
