import maplibregl, { type GeoJSONSource, type MapGeoJSONFeature, type MapMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { BBox, LatLon } from "@/shared/lib";
import { buildMapStyle, LAYER, SOURCE, type MapStyleInput } from "./map-style";
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

/** What is under the pointer, top layer first. */
export type MapHit = {
  point: LatLon;
  zoom: number;
  state: MapStateHit | null;
  county: MapCountyHit | null;
  field: MapFieldHit | null;
};

export type MapShape = { coordinates: number[][][]; buffered: boolean };

export type FieldMapHandle = {
  zoomIn: () => void;
  zoomOut: () => void;
  fitBBox: (bbox: BBox, maxZoom?: number) => void;
  flyTo: (point: LatLon, zoom: number) => void;
  getZoom: () => number;
};

type Props = {
  config: MapStyleInput;
  initialBBox: BBox;
  /** The selected field or buffered circle, drawn from its own geometry (one feature, never bulk). */
  selection: MapShape | null;
  pin: LatLon | null;
  ariaLabel: string;
  onClick?: (hit: MapHit) => void;
  onHover?: (hit: MapHit | null) => void;
  onZoomEnd?: (zoom: number) => void;
};

const HOVER_LAYERS = [LAYER.fieldsFill, LAYER.countiesFill, LAYER.statesFill];

function readHit(map: maplibregl.Map, e: MapMouseEvent): { hit: MapHit; features: MapGeoJSONFeature[] } {
  const layers = HOVER_LAYERS.filter((id) => map.getLayer(id));
  const features = map.queryRenderedFeatures(e.point, { layers });
  const zoom = map.getZoom();
  const pick = (layer: string) => features.find((f) => f.layer.id === layer);
  const st = pick(LAYER.statesFill);
  const co = zoom >= 6 ? pick(LAYER.countiesFill) : undefined;
  const fi = pick(LAYER.fieldsFill);
  const p = (f: MapGeoJSONFeature | undefined) => (f?.properties ?? {}) as Record<string, unknown>;
  const str = (v: unknown) => (v == null ? "" : String(v));
  return {
    features: [fi, co, st].filter((f): f is MapGeoJSONFeature => Boolean(f)),
    hit: {
      point: { lat: e.lngLat.lat, lon: e.lngLat.lng },
      zoom,
      state: st ? { fips: str(p(st).fips ?? st.id), name: str(p(st).name), postal: str(p(st).postal) } : null,
      county: co ? { fips: str(p(co).fips ?? co.id), name: str(p(co).name), state_fips: str(p(co).state_fips) } : null,
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
  { config, initialBBox, selection, pin, ariaLabel, onClick, onHover, onZoomEnd },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const handlers = useRef({ onClick, onHover, onZoomEnd });
  handlers.current = { onClick, onHover, onZoomEnd };
  const latest = useRef({ selection, pin });
  latest.current = { selection, pin };

  useImperativeHandle(ref, () => ({
    zoomIn: () => mapRef.current?.zoomIn(),
    zoomOut: () => mapRef.current?.zoomOut(),
    fitBBox: (bbox, maxZoom) =>
      mapRef.current?.fitBounds(toLngLatBounds(bbox), { padding: 48, maxZoom: maxZoom ?? 16, duration: reducedMotion() ? 0 : 800 }),
    flyTo: (point, zoom) =>
      mapRef.current?.flyTo({ center: [point.lon, point.lat], zoom, duration: reducedMotion() ? 0 : 800 }),
    getZoom: () => mapRef.current?.getZoom() ?? 0,
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
    // Tile errors (e.g. a deployment without the field file) must not break the page.
    map.on("error", () => undefined);

    let hovered: MapGeoJSONFeature[] = [];
    const setHover = (features: MapGeoJSONFeature[]) => {
      for (const f of hovered) if (f.id !== undefined) map.setFeatureState(f, { hover: false });
      hovered = features.filter((f) => f.id !== undefined).slice(0, 1);
      for (const f of hovered) map.setFeatureState(f, { hover: true });
    };

    map.on("load", () => {
      syncShapes(map, latest.current.selection, latest.current.pin);
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

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // initialBBox is only the first view; later moves go through the handle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [styleKey]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.isStyleLoaded()) syncShapes(map, selection, pin);
  }, [selection, pin]);

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
