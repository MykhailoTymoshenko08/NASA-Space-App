import type { MapStateHit, MapTownshipHit, MapView } from "./FieldMap";

/**
 * Focus by moving the map, without clicking: what is under the map center becomes the focus,
 * the same as a click on it would. A focused area follows the center when the user pans away.
 */

/** Zoom from which the county under the center gets the focus (a county fills most of the map). */
export const AUTO_COUNTY_ZOOM = 9;

export type ViewFocus = {
  state: MapStateHit | null;
  countyFips: string | null;
  /** Only at field scale. */
  township: MapTownshipHit | null;
};

export type ViewFocusOptions = {
  fieldMinZoom: number;
  /** Zoom at which the state under the center fills the map; null when unknown. */
  stateFitZoom: number | null;
  /**
   * "follow": state and county follow the center (explore map).
   * "fixed": the user entered the state and county, so only the township follows, and only in that county.
   */
  region: "follow" | "fixed";
};

/** The focus after the user moved the map to `view`. Zooming out is handled by the zoom floors in the widgets. */
export function focusForView(view: MapView, cur: ViewFocus, o: ViewFocusOptions): ViewFocus {
  const z = view.zoom;
  let { state, countyFips } = cur;

  if (o.region === "follow") {
    // State: once it fills the map; a focused state follows the center to the next state.
    const fillsMap = o.stateFitZoom !== null && z >= o.stateFitZoom - 0.5;
    if (view.state && view.state.fips !== state?.fips && (state !== null || fillsMap)) {
      state = view.state;
      countyFips = null;
    }
    // County: from AUTO_COUNTY_ZOOM; a focused county follows the center (null outside the field states).
    if (z >= AUTO_COUNTY_ZOOM || countyFips !== null) {
      const next = view.county?.fips ?? null;
      if (next !== countyFips) {
        countyFips = next;
        if (next && view.state) state = view.state;
      }
    }
  }

  // Township: the one under the center at field scale, inside the focused county if there is one.
  let township: MapTownshipHit | null = null;
  if (z >= o.fieldMinZoom && view.township) {
    const inCounty = countyFips === null || view.county?.fips === countyFips;
    if (inCounty) township = view.township.plssid === cur.township?.plssid ? cur.township : view.township;
  }
  return { state, countyFips, township };
}

/** True when `a` and `b` focus the same areas. */
export function sameFocus(a: ViewFocus, b: ViewFocus): boolean {
  return (
    a.state?.fips === b.state?.fips && a.countyFips === b.countyFips && a.township?.plssid === b.township?.plssid
  );
}
