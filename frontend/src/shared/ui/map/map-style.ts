import type { ExpressionSpecification, StyleSpecification } from "maplibre-gl";
import { apiUrl } from "@/shared/api";

/**
 * Map language from DS-Map, as a MapLibre style. Data comes only from our backend:
 * - boundary vector tiles: GET /tiles/boundaries/{z}/{x}/{y}.mvt (layers `states`, `counties`)
 * - field polygons: one PMTiles archive at coverage.field_tiles.url_template (layer `fields`)
 * Colors are read from the CSS tokens so hex values stay in tokens.css.
 */
export const LAYER = {
  statesFill: "states-fill",
  statesLine: "states-line",
  countiesFill: "counties-fill",
  countiesLine: "counties-line",
  fieldsFill: "fields-fill",
  fieldsLine: "fields-line",
  selectionFill: "selection-fill",
  selectionLine: "selection-line",
  selectionDashed: "selection-dashed",
  focusLine: "focus-line",
  pin: "pin",
} as const;

export const SOURCE = { boundaries: "boundaries", fields: "fields", selection: "selection", focus: "focus", pin: "pin" } as const;

/** Zoom bands from the contract: states < 7, counties 7 to 10, fields from field_tiles.min_zoom. */
export const ZOOM = { county: 7 } as const;

const token = (name: string, fallback: string) => {
  if (typeof document === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
};

export type MapStyleInput = {
  fieldTilesUrl: string | null;
  fieldMinZoom: number;
  fieldMaxZoom: number;
  supportedStates: readonly string[];
};

export function buildMapStyle(input: MapStyleInput): StyleSpecification {
  const c = {
    ground: token("--color-map-ground", "#e8e3d3"),
    state: token("--color-map-state", "#cbd7be"),
    stateFields: token("--color-map-state-fields", "#9fbe84"),
    stateHover: token("--color-map-state-hover", "#7fa463"),
    county: token("--color-map-county", "#d5e0c8"),
    regionLine: token("--color-map-region-line", "#8fa67c"),
    field: token("--color-map-field-1", "#b7c48e"),
    fieldLine: token("--color-map-field-line", "#6f7c4f"),
    selected: token("--color-map-field-selected", "#f0b93b"),
    outline: token("--color-map-outline", "#17211b"),
    pin: token("--color-wheat-500", "#e2a62b"),
    surface: token("--color-surface", "#fffdf8"),
  };
  const hovered: ExpressionSpecification = ["boolean", ["feature-state", "hover"], false];
  const supported: ExpressionSpecification = ["in", ["get", "postal"], ["literal", [...input.supportedStates]]];

  const style: StyleSpecification = {
    version: 8,
    sources: {
      [SOURCE.boundaries]: {
        type: "vector",
        tiles: [apiUrl("/tiles/boundaries/{z}/{x}/{y}.mvt")],
        minzoom: 0,
        maxzoom: 10,
        promoteId: { states: "fips", counties: "fips" },
      },
      [SOURCE.selection]: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
      [SOURCE.focus]: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
      [SOURCE.pin]: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
    },
    layers: [
      { id: "ground", type: "background", paint: { "background-color": c.ground } },
      {
        id: LAYER.statesFill,
        type: "fill",
        source: SOURCE.boundaries,
        "source-layer": "states",
        paint: {
          "fill-color": ["case", hovered, c.stateHover, supported, c.stateFields, c.state],
          "fill-opacity": ["interpolate", ["linear"], ["zoom"], ZOOM.county - 1, 1, ZOOM.county, 0],
        },
      },
      {
        id: LAYER.countiesFill,
        type: "fill",
        source: SOURCE.boundaries,
        "source-layer": "counties",
        minzoom: ZOOM.county - 1,
        paint: {
          "fill-color": ["case", hovered, c.stateFields, c.county],
          "fill-opacity": ["interpolate", ["linear"], ["zoom"], ZOOM.county - 1, 0, ZOOM.county, 1],
        },
      },
      {
        id: LAYER.countiesLine,
        type: "line",
        source: SOURCE.boundaries,
        "source-layer": "counties",
        minzoom: ZOOM.county - 1,
        paint: { "line-color": c.regionLine, "line-width": 1 },
      },
      {
        id: LAYER.statesLine,
        type: "line",
        source: SOURCE.boundaries,
        "source-layer": "states",
        paint: { "line-color": c.regionLine, "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.8, 8, 2] },
      },
      {
        id: LAYER.focusLine,
        type: "line",
        source: SOURCE.focus,
        paint: { "line-color": c.outline, "line-width": 2 },
      },
      {
        id: LAYER.selectionFill,
        type: "fill",
        source: SOURCE.selection,
        paint: { "fill-color": c.selected, "fill-opacity": ["case", ["==", ["get", "buffered"], true], 0.55, 0.9] },
      },
      {
        id: LAYER.selectionLine,
        type: "line",
        source: SOURCE.selection,
        filter: ["!=", ["get", "buffered"], true],
        paint: { "line-color": c.outline, "line-width": 2.5 },
      },
      {
        // A buffered circle is not a field outline: dashed, like the design sketch.
        id: LAYER.selectionDashed,
        type: "line",
        source: SOURCE.selection,
        filter: ["==", ["get", "buffered"], true],
        paint: { "line-color": c.outline, "line-width": 2.5, "line-dasharray": [3, 2.5] },
      },
      {
        id: LAYER.pin,
        type: "circle",
        source: SOURCE.pin,
        paint: { "circle-radius": 8, "circle-color": c.pin, "circle-stroke-color": c.outline, "circle-stroke-width": 2.5 },
      },
    ],
  };

  if (input.fieldTilesUrl) {
    style.sources[SOURCE.fields] = {
      type: "vector",
      url: `pmtiles://${input.fieldTilesUrl}`,
      minzoom: input.fieldMinZoom,
      maxzoom: input.fieldMaxZoom,
      promoteId: { fields: "field_id" },
    };
    const fieldLayers: StyleSpecification["layers"] = [
      {
        id: LAYER.fieldsFill,
        type: "fill",
        source: SOURCE.fields,
        "source-layer": "fields",
        minzoom: input.fieldMinZoom,
        paint: { "fill-color": ["case", hovered, c.stateFields, c.field] },
      },
      {
        id: LAYER.fieldsLine,
        type: "line",
        source: SOURCE.fields,
        "source-layer": "fields",
        minzoom: input.fieldMinZoom,
        paint: { "line-color": ["case", hovered, c.outline, c.fieldLine], "line-width": ["case", hovered, 2, 1] },
      },
    ];
    // Fields sit under the selection, above counties.
    const at = style.layers.findIndex((l) => l.id === LAYER.focusLine);
    style.layers.splice(at, 0, ...fieldLayers);
  }
  return style;
}
