import maplibregl, { type GeoJSONSource, type LngLat, type MapGeoJSONFeature, type PointLike } from "maplibre-gl";
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
import { isDesktopPointer, isNarrowScreen } from "./screen";
import { nearestHit } from "./touch-hit";
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
  /** The whole-country box: with no `bounds`, the map cannot pan or zoom out past its view. */
  outerBBox?: BBox;
  /**
   * The focused area (state or county): the map cannot pan or zoom out past the view that fits it, so
   * the user never drifts into the empty, masked land around it. Null: `outerBBox`.
   */
  bounds?: BBox | null;
  /**
   * The map fills the window, so with a mouse the wheel scrolls the page past it and Ctrl (Cmd on a Mac)
   * plus the wheel zooms. A trackpad pinch still zooms. Touch screens keep their gestures.
   */
  pageScrollsOverMap?: boolean;
  ariaLabel: string;
  onClick?: (hit: MapHit) => void;
  onHover?: (hit: MapHit | null) => void;
  onZoomEnd?: (zoom: number) => void;
  /** After a move, once its tiles are drawn: what is under the center (focus by moving the map). */
  onViewChange?: (view: MapView) => void;
};

const HOVER_LAYERS = [LAYER.fieldsFill, LAYER.townshipsFill, LAYER.countiesFill, LAYER.statesFill];
const MASK_LAYERS = [LAYER.stateMask, LAYER.countyMask, LAYER.townshipMask];

/** Where to read a hit: a screen point and the map position under it. */
type HitAt = { point: PointLike; lngLat: LngLat };

function readHit(map: maplibregl.Map, e: HitAt): { hit: MapHit; features: MapGeoJSONFeature[] } {
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

/** Layers a tap aims at, most specific first: the first one drawn at the current zoom is the target. */
const TAP_TARGETS = [LAYER.fieldsFill, LAYER.townshipsFill, LAYER.countiesFill, LAYER.statesFill];

function drawnAt(map: maplibregl.Map, id: string, zoom: number): boolean {
  const layer = map.getLayer(id);
  return layer !== undefined && zoom >= (layer.minzoom ?? 0) && zoom < (layer.maxzoom ?? 24);
}

/**
 * A touch tap (touch-hit.ts): when it misses the most specific layer drawn, read the hit at the nearest
 * pixel within reach that hits it, so a finger just off a small field or county still gets it.
 * Never moves a tap onto a masked area, or off one: a tap on a mask moves the focus there.
 */
function readTap(map: maplibregl.Map, e: HitAt): MapHit {
  const exact = readHit(map, e).hit;
  if (exact.outsideFocus) return exact;
  const target = TAP_TARGETS.find((id) => drawnAt(map, id, exact.zoom));
  if (!target) return exact;
  const masks = MASK_LAYERS.filter((id) => map.getLayer(id));
  const p = map.project(e.lngLat);
  const at = (dx: number, dy: number): [number, number] => [p.x + dx, p.y + dy];
  const hits = (pt: [number, number]) => map.queryRenderedFeatures(pt, { layers: [target] }).length > 0;
  if (hits(at(0, 0))) return exact;
  const visible = (pt: [number, number]) => masks.length === 0 || map.queryRenderedFeatures(pt, { layers: masks }).length === 0;
  const off = nearestHit(({ dx, dy }) => hits(at(dx, dy)) && visible(at(dx, dy)));
  if (!off) return exact;
  const point = at(off.dx, off.dy);
  return readHit(map, { point, lngLat: map.unproject(point) }).hit;
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
    bounds = null,
    pageScrollsOverMap = false,
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
  /** Zoom each limit box was opened at: where fitBBox ended on it, else the zoom when it became the limit. */
  const openZooms = useRef(new Map<string, number>());
  const limitBox = useRef<{ bbox: BBox; padding: number } | null>(null);
  limitBox.current = bounds
    ? { bbox: bounds, padding: FIT_PADDING }
    : outerBBox
      ? { bbox: outerBBox, padding: INITIAL_PADDING }
      : null;
  /** Hold the map in the focused area, else the country. Not mid-move: the moveend handler sets it then. */
  const applyLimit = useRef(() => {
    const map = mapRef.current;
    if (!map || map.isMoving()) return;
    const box = limitBox.current;
    if (!box) {
      map.setMaxBounds(null);
      return;
    }
    const key = box.bbox.join(",");
    if (!openZooms.current.has(key)) {
      // Not opened by fitBBox (focus by panning, the first view): keep what is on screen. On a wide screen
      // also allow the view that fits the whole box; a phone never shows a whole state or the country at once.
      const fit = map.cameraForBounds(toLngLatBounds(box.bbox), { padding: box.padding })?.zoom;
      const now = map.getZoom();
      openZooms.current.set(key, isNarrowScreen() || fit === undefined ? now : Math.min(now, fit));
    }
    limitView(map, box.bbox, box.padding, openZooms.current.get(key)!);
  }).current;

  useImperativeHandle(ref, () => ({
    zoomIn: () => mapRef.current?.zoomIn(),
    zoomOut: () => mapRef.current?.zoomOut(),
    fitBBox: (bbox, maxZoom, minZoom) => {
      const map = mapRef.current;
      if (!map) return;
      const duration = reducedMotion() ? 0 : 800;
      // Our own moves often leave the current limit (another state, back to the country): lift it now,
      // the new one is set when the move ends.
      map.setMaxBounds(null);
      const fit = map.cameraForBounds(toLngLatBounds(bbox), { padding: FIT_PADDING, maxZoom: maxZoom ?? 16 });
      if (fit?.zoom !== undefined) openZooms.current.set(bbox.join(","), Math.max(fit.zoom, minZoom ?? 0));
      if (minZoom !== undefined && fit?.zoom !== undefined && fit.zoom < minZoom) {
        // A small map cannot show the whole box at this zoom: center on it instead.
        map.flyTo({ center: [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2], zoom: minZoom, duration }, PROGRAMMATIC);
        return;
      }
      map.fitBounds(toLngLatBounds(bbox), { padding: FIT_PADDING, maxZoom: maxZoom ?? 16, duration }, PROGRAMMATIC);
    },
    flyTo: (point, zoom) => {
      const map = mapRef.current;
      if (!map) return;
      map.setMaxBounds(null);
      map.flyTo({ center: [point.lon, point.lat], zoom, duration: reducedMotion() ? 0 : 800 }, PROGRAMMATIC);
    },
    getZoom: () => mapRef.current?.getZoom() ?? 0,
    zoomForBBox: (bbox) => mapRef.current?.cameraForBounds(toLngLatBounds(bbox), { padding: FIT_PADDING })?.zoom ?? null,
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
      fitBoundsOptions: { padding: INITIAL_PADDING },
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      maxPitch: 0,
      cooperativeGestures: pageScrollsOverMap && isDesktopPointer(),
    });
    map.touchZoomRotate.disableRotation();
    mapRef.current = map;
    // Our own moves lift the limit to leave it (a limit set mid-flight would snap the camera); it is set
    // again when a move ends, and recomputed when the map resizes. A new map opens on its own first view.
    openZooms.current.clear();
    applyLimit();
    map.on("moveend", applyLimit);
    map.on("resize", applyLimit);
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
      // The first view (initialBBox) has no zoomend: report its zoom so the widgets start at the right scale.
      handlers.current.onZoomEnd?.(map.getZoom());
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
    // Taps get some reach (readTap); mouse clicks stay exact. The click after a tap follows its pointerdown.
    let lastPointer = "mouse";
    map.getCanvasContainer().addEventListener("pointerdown", (ev) => {
      lastPointer = ev.pointerType;
    });
    map.on("click", (e) => handlers.current.onClick?.(lastPointer === "mouse" ? readHit(map, e).hit : readTap(map, e)));
    map.on("zoomend", () => handlers.current.onZoomEnd?.(map.getZoom()));
    // Report the center once the move's boundary and survey tiles are drawn: the areas under the center
    // are read from them. Field tiles, by far the slowest, are not awaited (idle would), so a focus mask
    // follows the move at once instead of seconds later.
    let moved: { byUser: boolean } | null = null;
    const areasLoaded = () =>
      [SOURCE.boundaries, SOURCE.plss].every((id) => !map.getSource(id) || map.isSourceLoaded(id));
    const reportView = () => {
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
    };
    map.on("moveend", (e) => {
      moved = { byUser: !(e as { programmatic?: boolean }).programmatic };
      if (areasLoaded()) reportView();
    });
    map.on("render", () => {
      if (moved && !map.isMoving() && areasLoaded()) reportView();
    });
    map.on("idle", reportView);

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

  const boundsKey = bounds?.join(",") ?? "";
  useEffect(applyLimit, [boundsKey, applyLimit]);

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
/** Padding of fitBBox (and so of every focused area's view). */
const FIT_PADDING = 48;
/** Padding of the first, whole-country view. */
const INITIAL_PADDING = 24;

/**
 * Hold the map so it never shows land past the box: per axis, the box with its padding, or what the screen
 * shows at `zoom` (the zoom the box was opened at) when that is more. On a wide screen a tall state is fitted
 * whole, so the limit is that view; a phone opened on part of a wide state may pan along it, not off it.
 * Panning and zooming out stop at the limit; a zoom that would show more than it is refused.
 */
function limitView(map: maplibregl.Map, bbox: BBox, padding: number, zoom: number) {
  const { clientWidth: w, clientHeight: h } = map.getContainer();
  if (w === 0 || h === 0 || !Number.isFinite(zoom)) return;
  const sw = maplibregl.MercatorCoordinate.fromLngLat([bbox[0], bbox[1]]);
  const ne = maplibregl.MercatorCoordinate.fromLngLat([bbox[2], bbox[3]]);
  // Mercator units per screen pixel at that zoom (512 px tiles), with a hair of slack for rounding.
  const unit = 1.002 / (512 * 2 ** zoom);
  const cx = (sw.x + ne.x) / 2;
  const cy = (sw.y + ne.y) / 2;
  const halfW = Math.max((ne.x - sw.x) / 2 + padding * unit, (w / 2) * unit);
  const halfH = Math.max((sw.y - ne.y) / 2 + padding * unit, (h / 2) * unit);
  const min = new maplibregl.MercatorCoordinate(cx - halfW, cy + halfH).toLngLat();
  const max = new maplibregl.MercatorCoordinate(cx + halfW, cy - halfH).toLngLat();
  map.setMaxBounds([min.lng, min.lat, max.lng, max.lat]);
}
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
