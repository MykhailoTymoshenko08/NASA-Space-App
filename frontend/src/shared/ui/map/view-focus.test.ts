import { describe, expect, it } from "vitest";
import type { MapView } from "./FieldMap";
import { AUTO_COUNTY_ZOOM, focusForView, type ViewFocus } from "./view-focus";

const IA = { fips: "19", name: "Iowa", postal: "IA" };
const MO = { fips: "29", name: "Missouri", postal: "MO" };
const STORY = { fips: "19169", name: "Story", state_fips: "19" };
const BOONE = { fips: "19015", name: "Boone", state_fips: "19" };
const NEVADA = { plssid: "IA050830N0220W0", label: "T83N R22W", name: "Nevada Twp", bbox: [-93.5, 41.9, -93.4, 42] as const };
const GRANT = { plssid: "IA050830N0230W0", label: "T83N R23W", name: "Grant Twp", bbox: [-93.6, 41.9, -93.5, 42] as const };

const view = (zoom: number, over: Partial<MapView> = {}): MapView => ({
  zoom,
  center: { lat: 42, lon: -93.5 },
  state: IA,
  county: STORY,
  township: { ...NEVADA, bbox: [...NEVADA.bbox] },
  byUser: true,
  ...over,
});
const none: ViewFocus = { state: null, countyFips: null, township: null };
const follow = { fieldMinZoom: 11, stateFitZoom: 6.3, region: "follow" as const };
const fixed = { ...follow, region: "fixed" as const };

describe("focusForView", () => {
  it("focuses nothing while the whole country or a part of a state is in view", () => {
    expect(focusForView(view(4, { county: null, township: null }), none, follow)).toEqual(none);
  });

  it("focuses the state once it fills the map, then the county, then the township", () => {
    expect(focusForView(view(6), none, follow)).toEqual({ state: IA, countyFips: null, township: null });
    expect(focusForView(view(AUTO_COUNTY_ZOOM), none, follow)).toEqual({ state: IA, countyFips: "19169", township: null });
    expect(focusForView(view(11.5), none, follow).township?.plssid).toBe(NEVADA.plssid);
  });

  it("follows the center into the next county, township and state", () => {
    const cur: ViewFocus = { state: IA, countyFips: "19169", township: null };
    expect(focusForView(view(8.5, { county: BOONE }), cur, follow).countyFips).toBe("19015");
    const tw = focusForView(view(12, { township: { ...GRANT, bbox: [...GRANT.bbox] } }), { ...cur, township: null }, follow);
    expect(tw.township?.plssid).toBe(GRANT.plssid);
    expect(focusForView(view(9, { state: MO, county: null, township: null }), cur, follow)).toEqual({
      state: MO,
      countyFips: null,
      township: null,
    });
  });

  it("drops the township below field scale", () => {
    const cur: ViewFocus = { state: IA, countyFips: "19169", township: { ...NEVADA, bbox: [...NEVADA.bbox] } };
    expect(focusForView(view(10.5), cur, follow).township).toBeNull();
  });

  it("keeps an entered state and county, and focuses only townships inside that county", () => {
    const cur: ViewFocus = { state: IA, countyFips: "19169", township: null };
    expect(focusForView(view(12, { county: BOONE }), cur, fixed)).toEqual(cur);
    expect(focusForView(view(12), cur, fixed).township?.plssid).toBe(NEVADA.plssid);
    // No county entered (a pasted link): the township still follows.
    expect(focusForView(view(12), none, fixed).township?.plssid).toBe(NEVADA.plssid);
    expect(focusForView(view(12), none, fixed).state).toBeNull();
  });
});
