import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";
import { buildMapStyle, FIELD_LABEL_ZOOM, focusFilters, LAYER, townshipMinZoom, ZOOM } from "./map-style";

const input = {
  fieldTilesUrl: "http://localhost:8000/v1/tiles/fields.pmtiles",
  fieldMinZoom: 12,
  fieldMaxZoom: 14,
  supportedStates: ["IA", "IL", "NE"],
};

describe("buildMapStyle", () => {
  it("is a valid MapLibre style, with and without field tiles", () => {
    expect(validateStyleMin(buildMapStyle(input))).toEqual([]);
    expect(validateStyleMin(buildMapStyle({ ...input, fieldTilesUrl: null }))).toEqual([]);
  });

  it("loads label glyphs from our own origin", () => {
    expect(buildMapStyle(input).glyphs).toBe(`${window.location.origin}/fonts/{fontstack}/{range}.pbf`);
  });

  it("orders labels so saved fields win collisions, and field labels start at zoom 14", () => {
    const layers = buildMapStyle(input).layers;
    const ids = layers.map((l) => l.id);
    const at = (id: string) => ids.indexOf(id);
    expect(at(LAYER.fieldsLabel)).toBeLessThan(at(LAYER.stateMask));
    expect(at(LAYER.stateMask)).toBeLessThan(at(LAYER.countyLabels));
    expect(at(LAYER.countyLabels)).toBeLessThan(at(LAYER.places));
    expect(at(LAYER.places)).toBeLessThan(at(LAYER.stateLabels));
    expect(ids[ids.length - 1]).toBe(LAYER.savedLabel);
    expect(layers[at(LAYER.fieldsLabel)]!.minzoom).toBe(FIELD_LABEL_ZOOM);
  });

  it("hides everything outside the focus, and nothing without one", () => {
    const none = focusFilters(null);
    expect(none[LAYER.stateLabels]).toBeNull();
    expect(none[LAYER.places]).toBeNull();
    const state = focusFilters({ stateFips: "17", statePostal: "IL", countyFips: null });
    expect(state[LAYER.stateMask]).toEqual(["!=", ["get", "fips"], "17"]);
    expect(state[LAYER.places]).toEqual(["==", ["get", "state_postal"], "IL"]);
    expect(state[LAYER.stateLabels]).toEqual(none[LAYER.stateMask]);
    const county = focusFilters({ stateFips: "17", statePostal: "IL", countyFips: "17113" });
    expect(county[LAYER.countyMask]).toEqual(["!=", ["get", "fips"], "17113"]);
    expect(county[LAYER.places]).toEqual(["==", ["get", "county_fips"], "17113"]);
    expect(county[LAYER.countyLabels]).toEqual(["==", ["get", "fips"], "17113"]);
  });

  it("draws townships and sections above the fields and under the masks; field and town labels win", () => {
    const ids = buildMapStyle(input).layers.map((l) => l.id);
    const at = (id: string) => ids.indexOf(id);
    for (const id of [LAYER.townshipsFill, LAYER.townshipsLine, LAYER.sectionsLine]) {
      expect(at(id)).toBeGreaterThan(at(LAYER.fieldsLine));
      expect(at(id)).toBeLessThan(at(LAYER.selectionFill));
      expect(at(id)).toBeLessThan(at(LAYER.stateMask));
    }
    expect(at(LAYER.countyLabels)).toBeLessThan(at(LAYER.townshipLabels));
    expect(at(LAYER.sectionLabels)).toBeLessThan(at(LAYER.places));
    expect(at(LAYER.sectionLabels)).toBeLessThan(at(LAYER.stateMask));
    expect(at(LAYER.sectionLabels)).toBeLessThan(at(LAYER.fieldsLabel));
  });

  it("hides every other township's fields, towns and lines with a township in focus", () => {
    const f = focusFilters({
      stateFips: "19",
      statePostal: "IA",
      countyFips: "19169",
      township: { plssid: "IA050830N0220W0", bbox: [-93.5, 41.9, -93.4, 42.0] },
    });
    expect(f[LAYER.townshipMask]).toEqual(["!=", ["get", "plssid"], "IA050830N0220W0"]);
    expect(f[LAYER.focusTownshipLine]).toEqual(["==", ["get", "plssid"], "IA050830N0220W0"]);
    expect(f[LAYER.townshipsLine]).toEqual(["==", ["get", "plssid"], "IA050830N0220W0"]);
    expect((f[LAYER.places] as unknown[])[0]).toBe("within");
    expect(focusFilters({ stateFips: "19", statePostal: "IA", countyFips: "19169" })[LAYER.townshipMask]).toEqual(
      focusFilters(null)[LAYER.townshipMask],
    );
    // Every focus filter is valid on its layer.
    const style = buildMapStyle(input);
    for (const layer of style.layers) {
      const filter = f[layer.id];
      if (filter && layer.type !== "background") (layer as { filter?: unknown }).filter = filter;
    }
    expect(validateStyleMin(style)).toEqual([]);
  });

  it("shows townships at county scale only in a focused county", () => {
    expect(townshipMinZoom({ stateFips: "19", statePostal: "IA", countyFips: "19169" }, 11)).toBe(ZOOM.township);
    expect(townshipMinZoom({ stateFips: "19", statePostal: "IA", countyFips: null }, 11)).toBe(11);
    expect(townshipMinZoom(null, 11)).toBe(11);
  });

  it("shows township and section numbers only in the focused state or county", () => {
    expect(focusFilters(null)[LAYER.townshipLabels]).toBeNull();
    const state = focusFilters({ stateFips: "19", statePostal: "IA", countyFips: null });
    expect(state[LAYER.townshipLabels]).toEqual(["==", ["slice", ["get", "county_fips"], 0, 2], "19"]);
    const county = focusFilters({ stateFips: "19", statePostal: "IA", countyFips: "19169" });
    expect(county[LAYER.sectionLabels]).toEqual(["==", ["get", "county_fips"], "19169"]);
  });
});
