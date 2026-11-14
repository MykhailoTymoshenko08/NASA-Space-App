import maplibregl, { type GeoJSONSource, type MapGeoJSONFeature, type MapMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { BBox, LatLon } from "@/shared/lib";
import { fieldLabelPoints } from "./field-labels";
import {
  buildMapStyle,
  countyLabelText,
  FIELD_LABEL_ZOOM,
  focusFilters,
  LAYER,
  SOURCE,
  TOWNSHIP_LAYERS,
  townshipMinZoom,
  ZOOM,
  type MapFocus,
  type MapStyleInput,
} from "./map-style";
import s from "./field-map.module.css";

let pmtilesRegistered = false;
function registerPmtiles() {
  if (pmtilesRegistered) return;
  maplibregl.addProtocol("pmtiles", new Protocol().tile);
  pmtilesRegistered = true;
}

export type MapStateHit = { fips: string; name: string; postal: string };
export type MapCountyHit = { fips: string; name: string; state_fips: string };
export type MapFieldHit = { field_id: string; crop_class: string; area_ha: number | null };
/** A survey township (PLSS): `label` like "T84N R23W", `name` like "Grant Twp" or "" when it has none. */
export type MapTownshipHit = { plssid: string; label: string; name: string; bbox: BBox };

/** What is under the map center after the user moved the map (FieldMap onViewChange). */
export type MapView = {
  zoom: number;
  center: LatLon;
  /** Looked up through the focus masks: the center may be outside the focused area. */
  state: MapStateHit | null;
  county: MapCountyHit | null;
  township: MapTownshipHit | null;
  /** False for moves made through the handle (fitBBox, flyTo), true for drag, scroll, pinch and zoom buttons. */
  byUser: boolean;
};

/** What is under the pointer, top layer first. */
export type MapHit = {
  point: LatLon;
  zoom: number;
  state: MapStateHit | null;
  county: MapCountyHit | null;
  /** Only from ZOOM.township, where the townships are drawn. */
  township: MapTownshipHit | null;
  field: MapFieldHit | null;
  /**
   * True when the point is outside the focused area (hidden under a focus mask). The areas and field
   * under it are still filled in, so a click there can move the focus.
   */
  outsideFocus: boolean;
};

export type MapShape = { coordinates: number[][][]; buffered: boolean };

/** A saved field drawn with its name: outline for a field, marker for a saved point. */
export type MapSavedShape = {
  id: string;
  name: string;
  geometry: { type: "Polygon"; coordinates: number[][][] } | { type: "Point"; coordinates: number[] };
};

export type FieldMapHandle = {
  zoomIn: () => void;
  zoomOut: () => void;
  /** Fit the box; with `minZoom`, never end further out than that (centered on the box instead). */
  fitBBox: (bbox: BBox, maxZoom?: number, minZoom?: number) => void;
  flyTo: (point: LatLon, zoom: number) => void;
  getZoom: () => number;
  /** Zoom at which this box fills the map, as fitBBox would show it. */
  zoomForBBox: (bbox: BBox) => number | null;
};

type Props = {
  config: MapStyleInput;
  initialBBox: BBox;
  /** The selected field or buffered circle, drawn from its own geometry (one feature, never bulk). */
  selection: MapShape | null;
  pin: LatLon | null;
  /** The signed-in user's saved fields, labeled with their names. */
  saved?: readonly MapSavedShape[];
  /** Area the user drilled into; everything else is hidden. */
  focus?: MapFocus | null;
  /** Townships at county scale only in the focused county; elsewhere only with the fields. */
  townshipsFollowFocus?: boolean;
  /** The map cannot be zoomed out further than this box (the whole-country view). */
  outerBBox?: BBox;
  ariaLabel: string;
  onClick?: (hit: MapHit) => void;
  onHover?: (hit: MapHit | null) => void;
  onZoomEnd?: (zoom: number) => void;
  /** After a move, once its tiles are drawn: what is under the center (focus by moving the map). */
  onViewChange?: (view: MapView) => void;
};

const HOVER_LAYERS = [LAYER.fieldsFill, LAYER.townshipsFill, LAYER.countiesFill, LAYER.statesFill];
const MASK_LAYERS = [LAYER.stateMask, LAYER.countyMask, LAYER.townshipMask];

function readHit(map: maplibregl.Map, e: Pick<MapMouseEvent, "point" | "lngLat">): { hit: MapHit; features: MapGeoJSONFeature[] } {
  const layers = HOVER_LAYERS.filter((id) => map.getLayer(id));
  const masks = MASK_LAYERS.filter((id) => map.getLayer(id));
  const outsideFocus = masks.length > 0 && map.queryRenderedFeatures(e.point, { layers: masks }).length > 0;
  // Features are read under the masks too (the layers below a mask still hold them).
  const features = map.queryRenderedFeatures(e.point, { layers });
  const zoom = map.getZoom();
  const pick = (layer: string) => features.find((f) => f.layer.id === layer);
  const st = pick(LAYER.statesFill);
  const co = zoom >= ZOOM.countyLines ? pick(LAYER.countiesFill) : undefined;
  const tw = zoom >= ZOOM.township ? pick(LAYER.townshipsFill) : undefined;
  const fi = pick(LAYER.fieldsFill);
  const p = (f: MapGeoJSONFeature | undefined) => (f?.properties ?? {}) as Record<string, unknown>;
  const str = (v: unknown) => (v == null ? "" : String(v));
  const num = (v: unknown) => (typeof v === "number" ? v : Number(v));
  const twBBox = tw ? ([num(p(tw).w), num(p(tw).s), num(p(tw).e), num(p(tw).n)] as BBox) : null;
  return {
    // Most specific first: only the first one is hovered. Nothing under a mask is visible to hover.
    features: outsideFocus ? [] : [fi, tw, co, st].filter((f): f is MapGeoJSONFeature => Boolean(f)),
    hit: {
      point: { lat: e.lngLat.lat, lon: e.lngLat.lng },
      zoom,
      outsideFocus,
      state: st ? { fips: str(p(st).fips ?? st.id), name: str(p(st).name), postal: str(p(st).postal) } : null,
      county: co ? { fips: str(p(co).fips ?? co.id), name: str(p(co).name), state_fips: str(p(co).state_fips) } : null,
      township:
        tw && twBBox && twBBox.every(Number.isFinite)
          ? { plssid: str(p(tw).plssid ?? tw.id), label: str(p(tw).label), name: str(p(tw).name), bbox: twBBox }
          : null,
      field: fi
        ? {
            field_id: str(p(fi).field_id ?? fi.id),
            crop_class: str(p(fi).crop_class),
            area_ha: typeof p(fi).area_ha === "number" ? (p(fi).area_ha as number) : null,
          }
        : null,
    },
  };
}

const toLngLatBounds = (b: BBox): [[number, number], [number, number]] => [
  [b[0], b[1]],
  [b[2], b[3]],
];

/**
 * MapLibre map of our boundary tiles and field PMTiles. A thin, controlled wrapper:
 * parents pass the selection and pin, and get clicks and hovers back. Draw controls live outside it.
 */
export const FieldMap = forwardRef<FieldMapHandle, Props>(function FieldMap(
  {
    config,
    initialBBox,
    selection,
    pin,
    saved = NO_SAVED,
    focus = null,
    townshipsFollowFocus = false,
    outerBBox,
    ariaLabel,
    onClick,
    onHover,
    onZoomEnd,
    onViewChange,
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  // Set on "load". Not map.isStyleLoaded(): that is false while any tile loads, and updates made
  // then (focus, selection, saved fields) were silently skipped.
  const readyRef = useRef(false);
  const handlers = useRef({ onClick, onHover, onZoomEnd, onViewChange });
  handlers.current = { onClick, onHover, onZoomEnd, onViewChange };
  const latest = useRef({ selection, pin, saved, focus, townshipsFollowFocus });
  latest.current = { selection, pin, saved, focus, townshipsFollowFocus };

  useImperativeHandle(ref, () => ({
    zoomIn: () => mapRef.current?.zoomIn(),
    zoomOut: () => mapRef.current?.zoomOut(),
    fitBBox: (bbox, maxZoom, minZoom) => {
      const map = mapRef.current;
      if (!map) return;
      const duration = reducedMotion() ? 0 : 800;
      const fit = map.cameraForBounds(toLngLatBounds(bbox), { padding: 48, maxZoom: maxZoom ?? 16 });
      if (minZoom !== undefined && fit?.zoom !== undefined && fit.zoom < minZoom) {
        // A small map cannot show the whole box at this zoom: center on it instead.
        map.flyTo({ center: [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2], zoom: minZoom, duration }, PROGRAMMATIC);
        return;
      }
      map.fitBounds(toLngLatBounds(bbox), { padding: 48, maxZoom: maxZoom ?? 16, duration }, PROGRAMMATIC);
    },
    flyTo: (point, zoom) =>
      mapRef.current?.flyTo({ center: [point.lon, point.lat], zoom, duration: reducedMotion() ? 0 : 800 }, PROGRAMMATIC),
    getZoom: () => mapRef.current?.getZoom() ?? 0,
    zoomForBBox: (bbox) => mapRef.current?.cameraForBounds(toLngLatBounds(bbox), { padding: 48 })?.zoom ?? null,
  }));

  // Create once per style config.
  const styleKey = `${config.fieldTilesUrl}|${config.fieldMinZoom}|${config.fieldMaxZoom}|${config.supportedStates.join(",")}`;
  useEffect(() => {
    if (!containerRef.current) return;
    registerPmtiles();
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: buildMapStyle(config),
      bounds: toLngLatBounds(initialBBox),
      fitBoundsOptions: { padding: 24 },
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      maxPitch: 0,
    });
    map.touchZoomRotate.disableRotation();
    mapRef.current = map;
    // Zoom out no further than the whole-country view (recomputed when the map resizes).
    const limitZoom = () => {
      if (!outerBBox) return;
      const z = map.cameraForBounds(toLngLatBounds(outerBBox), { padding: 24 })?.zoom;
      if (z !== undefined) map.setMinZoom(Math.max(0, z));
    };
    limitZoom();
    map.on("resize", limitZoom);
    // Tile errors (e.g. a deployment without the field file) must not break the page.
    map.on("error", () => undefined);

    let hovered: MapGeoJSONFeature[] = [];
    const setHover = (features: MapGeoJSONFeature[]) => {
      for (const f of hovered) if (f.id !== undefined) map.setFeatureState(f, { hover: false });
      hovered = features.filter((f) => f.id !== undefined).slice(0, 1);
      for (const f of hovered) map.setFeatureState(f, { hover: true });
    };

    map.on("load", () => {
      readyRef.current = true;
      syncShapes(map, latest.current.selection, latest.current.pin);
      syncSaved(map, latest.current.saved);
      syncFocus(map, latest.current.focus, latest.current.townshipsFollowFocus, config.fieldMinZoom);
    });
    // One label point per field, from the field tiles loaded for this view (see map-style.ts).
    const labelZoom = Math.max(FIELD_LABEL_ZOOM, config.fieldMinZoom);
    let labelKey = "";
    map.on("idle", () => {
      const src = map.getSource(SOURCE.fieldLabels) as GeoJSONSource | undefined;
      if (!src) return;
      const features = map.getZoom() >= labelZoom ? map.querySourceFeatures(SOURCE.fields, { sourceLayer: "fields" }) : [];
      // setData renders again and fires another idle: only update when the set of pieces changed.
      const key = features.length ? `${features.length}:${String(features[0]?.id)}:${String(features[features.length - 1]?.id)}` : "";
      if (key === labelKey) return;
      labelKey = key;
      src.setData(fieldLabelPoints(features));
    });
    map.on("mousemove", (e) => {
      const { hit, features } = readHit(map, e);
      setHover(features);
      map.getCanvas().style.cursor = features.length ? "pointer" : "";
      handlers.current.onHover?.(hit);
    });
    map.on("mouseout", () => {
      setHover([]);
      handlers.current.onHover?.(null);
    });
    map.on("click", (e) => handlers.current.onClick?.(readHit(map, e).hit));
    map.on("zoomend", () => handlers.current.onZoomEnd?.(map.getZoom()));
    // Report the center once the move's tiles are drawn (idle), not on moveend: the areas under the
    // center are read from the rendered tiles.
    let moved: { byUser: boolean } | null = null;
    map.on("moveend", (e) => {
      moved = { byUser: !(e as { programmatic?: boolean }).programmatic };
    });
    map.on("idle", () => {
      if (!moved || !handlers.current.onViewChange) return;
      const { byUser } = moved;
      moved = null;
      const c = map.getCenter();
      const { hit } = readHit(map, { point: map.project(c), lngLat: c });
      handlers.current.onViewChange({
        zoom: hit.zoom,
        center: hit.point,
        state: hit.state,
        county: hit.county,
        township: hit.township,
        byUser,
      });
    });

    return () => {
      readyRef.current = false;
      map.remove();
      mapRef.current = null;
    };
    // initialBBox is only the first view; later moves go through the handle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [styleKey]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && readyRef.current) syncShapes(map, selection, pin);
  }, [selection, pin]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && readyRef.current) syncSaved(map, saved);
  }, [saved]);

  const focusKey = focus ? `${focus.stateFips}|${focus.countyFips ?? ""}|${focus.township?.plssid ?? ""}` : "";
  useEffect(() => {
    const map = mapRef.current;
    if (map && readyRef.current) syncFocus(map, latest.current.focus, townshipsFollowFocus, config.fieldMinZoom);
    // config.fieldMinZoom changes rebuild the map (styleKey), which syncs on load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusKey, townshipsFollowFocus]);

  return (
    <div
      ref={containerRef}
      className={s.map}
      role="application"
      aria-label={ariaLabel}
      aria-roledescription="map"
    />
  );
});

const NO_SAVED: readonly MapSavedShape[] = [];
/** Event data of the handle's camera moves, so onViewChange can tell them from the user's. */
const PROGRAMMATIC = { programmatic: true };

function syncFocus(map: maplibregl.Map, focus: MapFocus | null, townshipsFollowFocus: boolean, fieldMinZoom: number) {
  for (const [layer, filter] of Object.entries(focusFilters(focus))) {
    if (map.getLayer(layer)) map.setFilter(layer, filter);
  }
  if (map.getLayer(LAYER.countyLabels)) map.setLayoutProperty(LAYER.countyLabels, "text-field", countyLabelText(focus !== null));
  const minZoom = townshipsFollowFocus ? townshipMinZoom(focus, fieldMinZoom) : ZOOM.township;
  for (const id of TOWNSHIP_LAYERS) {
    const layer = map.getLayer(id);
    if (layer) map.setLayerZoomRange(id, minZoom, layer.maxzoom ?? 24);
  }
}

function syncSaved(map: maplibregl.Map, saved: readonly MapSavedShape[]) {
  const src = map.getSource(SOURCE.saved) as GeoJSONSource | undefined;
  src?.setData({
    type: "FeatureCollection",
    features: saved.map((f) => ({ type: "Feature", id: f.id, properties: { name: f.name }, geometry: f.geometry })),
  });
}

function syncShapes(map: maplibregl.Map, selection: MapShape | null, pin: LatLon | null) {
  const sel = map.getSource(SOURCE.selection) as GeoJSONSource | undefined;
  sel?.setData({
    type: "FeatureCollection",
    features: selection
      ? [
          {
            type: "Feature",
            properties: { buffered: selection.buffered },
            geometry: { type: "Polygon", coordinates: selection.coordinates },
          },
        ]
      : [],
  });
  const pinSrc = map.getSource(SOURCE.pin) as GeoJSONSource | undefined;
  pinSrc?.setData({
    type: "FeatureCollection",
    features: pin ? [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [pin.lon, pin.lat] } }] : [],
  });
}

const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
