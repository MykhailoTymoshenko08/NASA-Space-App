import { useEffect, useMemo, useRef, useState } from "react";
import { fetchField, isBuffered, resolveFieldAt } from "@/entities/field";
import { CONUS_BBOX, mapConfigFrom, stateBBox, useCounty, useCoverage, useStates } from "@/entities/region";
import { useSavedFieldShapes } from "@/entities/saved-field";
import { useSession } from "@/entities/session";
import { friendlyMessage, type County, type FieldSelection, type SelectionSource } from "@/shared/api";
import { bboxOfRing, type BBox, type LatLon } from "@/shared/lib";
import { Icon } from "@/shared/ui/icon";
import {
  COUNTY_FIT_MIN_ZOOM,
  FieldMap,
  focusForView,
  isNarrowScreen,
  tapWord,
  ZOOM,
  type FieldMapHandle,
  type MapFocus,
  type MapHit,
  type MapStateHit,
  type MapTownshipHit,
  type MapView,
} from "@/shared/ui/map";
import {
  CROP_LEGEND_ITEMS,
  MapBottomBar,
  MapHint,
  MapLegend,
  MapStage,
  MapZoomControls,
  SAVED_LEGEND_ITEM,
  SECTION_LEGEND_ITEM,
  TOWNSHIP_LEGEND_ITEM,
  type LegendItem,
} from "@/shared/ui/map-overlay";
import s from "./pick-map.module.css";

/** The state and county the map is focused on. */
type Place = { state: MapStateHit | null; county: County | null };
const NO_PLACE: Place = { state: null, county: null };

export type PickMapPlace = { stateFips: string | null; county: County | null };

type Props = {
  /** State chosen in the picker; the map fits it. */
  stateFips: string | null;
  /** County chosen in the picker; the map fits it. */
  county: County | null;
  /** Point from a pasted link or coordinates; shown as a pin. */
  pin: LatLon | null;
  /** Current selection; drawn on the map and the map fits to it. */
  selection: FieldSelection | null;
  /** Shown in the bar when there is no state or county (e.g. the pasted point). */
  placeLabel: string | null;
  onSelect: (selection: FieldSelection) => void;
  /**
   * The user went to a state or county on the map, or zoomed out of it: the picker follows.
   * Without it (link or coordinates), the map finds its way on its own.
   */
  onPlaceChange?: (place: PickMapPlace) => void;
};

/**
 * Pick-a-field map. It opens on the whole country (on a phone, on the field states: a state is too small
 * to tap at the country view). A click goes one level down: state, county, survey township, then an
 * estimated field area. A field feature calls GET /fields/{id}; any other click at field scale calls
 * POST /fields/resolve (snap or circle). The state and county stay in step with the picker.
 * Focus: the state and county hide everything else. At field scale, the survey township under the map
 * center hides every other township (shared/ui/map/view-focus.ts), inside the county.
 */
export function PickMap({ stateFips, county, pin, selection, placeLabel, onSelect, onPlaceChange }: Props) {
  const coverage = useCoverage();
  const states = useStates();
  const config = useMemo(() => mapConfigFrom(coverage.data), [coverage.data]);
  const mapRef = useRef<FieldMapHandle>(null);
  const session = useSession();
  const saved = useSavedFieldShapes(session.user?.id ?? null);
  const narrow = isNarrowScreen();
  const startBBox = useMemo(
    () => (narrow && coverage.data ? (coverage.data.bounds as BBox) : CONUS_BBOX),
    [narrow, coverage.data],
  );
  const [zoom, setZoom] = useState(4);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [place, setPlaceState] = useState<Place>(NO_PLACE);
  // Read by effects and map handlers, which may run before the next render.
  const placeRef = useRef(place);
  /** Focused township at field scale, with its state (the focus needs one when there is no place). */
  const [area, setArea] = useState<{ state: MapStateHit | null; township: MapTownshipHit } | null>(null);
  /** A county clicked on the map: the tiles carry no bbox, so it is fitted once GET /geo/counties/{fips} arrives. */
  const [pendingCounty, setPendingCounty] = useState<{ fips: string; point: LatLon } | null>(null);
  const pendingCountyQuery = useCounty(pendingCounty?.fips ?? null);
  const fieldScale = zoom >= config.fieldMinZoom;
  const tap = tapWord();

  const setPlace = (next: Place) => {
    placeRef.current = next;
    setPlaceState(next);
    setArea(null);
  };
  /** A move made on the map: tell the picker. */
  const goPlace = (next: Place) => {
    setPlace(next);
    onPlaceChange?.({ stateFips: next.state?.fips ?? null, county: next.county });
  };

  const stateOf = (fips: string) => states.data?.find((x) => x.fips === fips);
  const stateOfCounty = (c: County): MapStateHit => ({
    fips: c.state_fips,
    postal: c.state_postal,
    name: stateOf(c.state_fips)?.name ?? c.state_postal,
  });
  const fitCounty = (c: County) => mapRef.current?.fitBBox(c.bbox as BBox, config.fieldMinZoom - 1, COUNTY_FIT_MIN_ZOOM);
  // A phone fits a whole state below the zoom where counties show: zoom in to the counties instead.
  const fitState = (bbox: BBox) => mapRef.current?.fitBBox(bbox, undefined, narrow ? ZOOM.countyLines : undefined);

  // The picker changed: follow it. A change made on the map comes back equal and does nothing.
  const controlled = onPlaceChange !== undefined;
  useEffect(() => {
    const cur = placeRef.current;
    if (county) {
      if (county.fips === cur.county?.fips) return;
      setPlace({ state: stateOfCounty(county), county });
      fitCounty(county);
    } else if (stateFips) {
      if (stateFips === cur.state?.fips && cur.county === null) return;
      const st = stateOf(stateFips);
      if (!st) return; // Runs again once the states arrive.
      setPlace({ state: { fips: st.fips, name: st.name, postal: st.postal }, county: null });
      fitState(st.bbox as BBox);
    } else if (controlled && (cur.state || cur.county)) {
      setPlace(NO_PLACE);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stateFips, county, states.data, controlled]);

  useEffect(() => {
    if (!pendingCounty) return;
    const c = pendingCountyQuery.data;
    if (c?.fips === pendingCounty.fips) {
      setPendingCounty(null);
      goPlace({ state: stateOfCounty(c), county: c });
      fitCounty(c);
    } else if (pendingCountyQuery.isError) {
      // The county cannot be loaded: go straight to the fields where the user clicked.
      setPendingCounty(null);
      mapRef.current?.flyTo(pendingCounty.point, config.fieldMinZoom + 0.5);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingCounty, pendingCountyQuery.data, pendingCountyQuery.isError]);

  // A pasted point may be anywhere: drop the state and county, so their masks do not hide it.
  useEffect(() => {
    if (pin) setPlace(NO_PLACE);
  }, [pin]);

  // A field picked on this map is already in view: moving there again would only jump the camera.
  const pickedHere = useRef<FieldSelection | null>(null);
  useEffect(() => {
    if (selection && selection === pickedHere.current) return;
    const ring = selection?.geometry.coordinates[0];
    if (ring && ring.length > 0) {
      const b = selection?.bbox ?? bboxOfRing(ring);
      mapRef.current?.fitBBox(b as BBox, 16);
    } else if (pin) {
      mapRef.current?.flyTo(pin, config.fieldMinZoom + 1);
    }
  }, [selection, pin, config.fieldMinZoom]);

  const tw = area ? { plssid: area.township.plssid, bbox: area.township.bbox } : null;
  const focus: MapFocus | null = place.state
    ? { stateFips: place.state.fips, statePostal: place.state.postal, countyFips: place.county?.fips ?? null, township: tw }
    : area?.state
      ? { stateFips: area.state.fips, statePostal: area.state.postal, countyFips: null, township: tw }
      : null;

  // The map stays in the focused county, else state (shared/ui/map/FieldMap.tsx `bounds`).
  const focusState = place.state ?? area?.state ?? null;
  const bounds = (place.county?.bbox as BBox | undefined) ?? (focusState ? stateBBox(focusState.fips) : null);

  /** Zoom below which a focus ends: one level under the zoom that fits the area. */
  const floorFor = (bbox: number[] | undefined) => {
    const z = bbox ? mapRef.current?.zoomForBBox(bbox as BBox) : null;
    return z != null ? z - 1 : null;
  };

  // Every move counts for the township, ours too: fitting a selection or a pasted point focuses its township.
  // Zooming well out of the county or state (the user's own move) leaves it, as on the explore map.
  const onViewChange = (view: MapView) => {
    const cur = placeRef.current;
    if (view.byUser && !pendingCounty) {
      const stateFloor = cur.state ? floorFor(stateOf(cur.state.fips)?.bbox) : null;
      const countyFloor = cur.county ? floorFor(cur.county.bbox) : null;
      if (stateFloor !== null && view.zoom < stateFloor) {
        goPlace(NO_PLACE);
        return;
      }
      if (countyFloor !== null && view.zoom < Math.min(countyFloor, config.fieldMinZoom - 1)) {
        goPlace({ state: cur.state, county: null });
        return;
      }
    }
    const now = { state: null, countyFips: cur.county?.fips ?? null, township: area?.township ?? null };
    const next = focusForView(view, now, { fieldMinZoom: config.fieldMinZoom, stateFitZoom: null, region: "fixed" });
    if (next.township?.plssid === area?.township.plssid) return;
    setArea(next.township ? { state: view.state, township: next.township } : null);
  };

  const pick = async (load: () => Promise<FieldSelection>) => {
    setBusy(true);
    setError(null);
    try {
      const picked = await load();
      pickedHere.current = picked;
      onSelect(picked);
    } catch (err) {
      setError(friendlyMessage(err));
    } finally {
      setBusy(false);
    }
  };

  /** A township fills the map. Its focus is set now, so the other townships are hidden during the move. */
  const goTownship = (t: MapTownshipHit, state: MapStateHit | null) => {
    setArea({ state: state ?? placeRef.current.state, township: t });
    mapRef.current?.fitBBox(t.bbox, undefined, config.fieldMinZoom + 0.25);
  };

  const onClick = (rawHit: MapHit) => {
    setError(null);
    const cur = placeRef.current;
    if (rawHit.zoom >= config.fieldMinZoom) {
      if (rawHit.outsideFocus) {
        if (cur.county && rawHit.county?.fips !== cur.county.fips) {
          setError(`That is outside ${cur.county.name} County. Zoom out to choose another county.`);
          return;
        }
        // Another township: focus it.
        if (rawHit.township) goTownship(rawHit.township, rawHit.state);
        return;
      }
      const source: SelectionSource = "map_click";
      if (rawHit.field?.field_id) void pick(() => fetchField(rawHit.field!.field_id));
      else void pick(() => resolveFieldAt(rawHit.point, source));
      return;
    }

    // Below field scale a click goes one level down. A hidden state or county is reached the same way,
    // but never straight into one of its townships.
    const hit = rawHit.outsideFocus ? { ...rawHit, township: null } : rawHit;
    if (hit.township) {
      goTownship(hit.township, hit.state);
      return;
    }
    if (hit.county && hit.zoom >= ZOOM.countyLines) {
      if (hit.county.fips === cur.county?.fips) mapRef.current?.flyTo(hit.point, config.fieldMinZoom + 0.5);
      else setPendingCounty({ fips: hit.county.fips, point: hit.point });
      return;
    }
    if (hit.state) {
      const st = stateOf(hit.state.fips);
      if (st) {
        goPlace({ state: hit.state, county: null });
        fitState(st.bbox as BBox);
        return;
      }
      setError(
        `No field outlines in ${hit.state.name} yet. Zoom in to your field and ${tap.toLowerCase()} it: we use a circle around that point.`,
      );
    }
    mapRef.current?.flyTo(hit.point, hit.zoom < ZOOM.county ? Math.min(hit.zoom + 2, ZOOM.county) : config.fieldMinZoom + 0.5);
  };

  const buffered = selection !== null && isBuffered(selection);
  const line = "var(--color-map-region-line)";
  const legend: LegendItem[] = fieldScale
    ? [
        ...CROP_LEGEND_ITEMS,
        { label: buffered ? "Circle around your point" : "Selected", fill: "var(--color-map-field-selected)", line: "var(--color-map-outline)" },
        ...(saved.length > 0 ? [SAVED_LEGEND_ITEM] : []),
        SECTION_LEGEND_ITEM,
      ]
    : !place.state && zoom < ZOOM.countyLines
      ? [
          { label: "Field outlines available", fill: "var(--color-map-state-fields)", line },
          { label: "Point analysis only", fill: "var(--color-map-state)", line },
        ]
      : place.county
        ? [{ label: "County", fill: "var(--color-map-county)", line }, TOWNSHIP_LEGEND_ITEM]
        : [{ label: "County", fill: "var(--color-map-county)", line }];

  const hint = error
    ? error
    : pendingCounty
      ? "Finding the county…"
      : busy
        ? "Finding the field…"
        : !fieldScale
          ? place.county
            ? `${tap} your township, or where your field is, to zoom in`
            : place.state
              ? `${tap} your county to zoom in`
              : `${tap} your state to zoom in`
          : buffered
            ? "No field outlines here. We use a circle around your point"
            : selection
              ? "Selected. Its details are under Selected field"
              : `${tap} an estimated field area to select it`;

  // No name for the whole country: the map shows it. The instruction takes the title's place.
  const title = place.county
    ? `${place.county.name} County, ${place.county.state_postal}`
    : place.state
      ? place.state.name
      : placeLabel;
  const where = controlled ? "on the map or in the list" : "on the map, or paste a link or coordinates";
  const scaleText = fieldScale
    ? "Field scale. Outlines are estimates from USDA crop maps."
    : place.county
      ? "County scale. Zoom in to see estimated field areas."
      : place.state
        ? `Choose your county ${where}.`
        : `Choose your state ${where}.`;

  const showStart = () => mapRef.current?.fitBBox(startBBox);
  const back: { label: string; go: () => void } | null =
    place.county && fieldScale
      ? { label: "Back to county", go: () => fitCounty(place.county!) }
      : place.county && place.state
        ? {
            label: `Back to ${place.state.name}`,
            go: () => {
              const st = stateOf(place.state!.fips);
              goPlace({ state: place.state, county: null });
              if (st) fitState(st.bbox as BBox);
            },
          }
        : place.state
          ? {
              label: "All states",
              go: () => {
                goPlace(NO_PLACE);
                showStart();
              },
            }
          : selection
            ? {
                label: "Back to field",
                go: () =>
                  mapRef.current?.fitBBox((selection.bbox ?? bboxOfRing(selection.geometry.coordinates[0] ?? [])) as BBox, 16),
              }
            : null;

  return (
    <MapStage height={700}>
      <div className={s.bar}>
        <div className={s.barText}>
          {title ? (
            <>
              <div className={s.place}>{title}</div>
              <div className={s.scale}>{scaleText}</div>
            </>
          ) : (
            <div className={s.lead}>{scaleText}</div>
          )}
        </div>
        {back && (
          <button type="button" className={s.back} onClick={back.go}>
            <Icon name="arrow-left" size={18} />
            {back.label}
          </button>
        )}
      </div>
      <div className={s.mapArea}>
        <FieldMap
          ref={mapRef}
          config={config}
          initialBBox={startBBox}
          selection={selection ? { coordinates: selection.geometry.coordinates, buffered } : null}
          pin={pin}
          saved={saved}
          focus={focus}
          townshipsFollowFocus
          outerBBox={CONUS_BBOX}
          bounds={bounds}
          ariaLabel={`Map of ${title ?? "the United States"}`}
          onClick={onClick}
          onZoomEnd={setZoom}
          onViewChange={onViewChange}
        />
        <MapZoomControls
          onZoomIn={() => mapRef.current?.zoomIn()}
          onZoomOut={() => mapRef.current?.zoomOut()}
        />
        <MapBottomBar>
          <MapLegend items={legend} />
          <MapHint>{coverage.isError ? friendlyMessage(coverage.error) : hint}</MapHint>
        </MapBottomBar>
      </div>
    </MapStage>
  );
}
