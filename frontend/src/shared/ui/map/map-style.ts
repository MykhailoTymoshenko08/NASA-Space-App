import type { ExpressionSpecification, FilterSpecification, StyleSpecification } from "maplibre-gl";
import { apiUrl } from "@/shared/api";
import type { BBox } from "@/shared/lib";
import { cropColorExpression } from "./crops";

/**
 * Map language from DS-Map, as a MapLibre style. Data comes only from our backend:
 * - boundary vector tiles: GET /tiles/boundaries/{z}/{x}/{y}.mvt (polygon layers `states`, `counties`;
 *   label point layers `state_labels`, `county_labels`, `places`)
 * - field polygons: one PMTiles archive at coverage.field_tiles.url_template (layer `fields`)
 * - survey townships and sections (PLSS) in the field states: GET /tiles/plss/{z}/{x}/{y}.mvt (polygon layers
 *   `townships`, `sections`; label point layers `township_labels`, `section_labels`). The step between a
 *   county and its fields: farmers know their township and section from deeds and plat books.
 * - label glyphs: self-hosted in public/fonts (see its README), so no request leaves the app
 * Colors are read from the CSS tokens so hex values stay in tokens.css.
 *
 * Labels by zoom: state names below 8 (hidden in a focused state), county names 5.5 to 13 (with the
 * county lines), towns only at field scale (largest first). Counties and towns exist only in the field states; other states show just a name.
 * Township lines and names from 8 (names until fields show), section lines and numbers from 11.
 * Field crop and acres from 14, saved field names at every zoom (they win label collisions).
 *
 * Focus: with a state (or county, or survey township) in focus, masks in the ground color cover every
 * other state (or county, or township), fields included, and the place labels show only the focused
 * area (`focusFilters`).
 */
export const LAYER = {
  statesFill: "states-fill",
  statesLine: "states-line",
  countiesFill: "counties-fill",
  countiesLine: "counties-line",
  townshipsFill: "townships-fill",
  townshipsLine: "townships-line",
  sectionsLine: "sections-line",
  fieldsFill: "fields-fill",
  fieldsLine: "fields-line",
  selectionFill: "selection-fill",
  selectionLine: "selection-line",
  selectionDashed: "selection-dashed",
  focusLine: "focus-line",
  pin: "pin",
  fieldsLabel: "fields-label",
  countyLabels: "county-labels",
  townshipLabels: "township-labels",
  sectionLabels: "section-labels",
  places: "places",
  stateLabels: "state-labels",
  savedLine: "saved-line",
  savedPoint: "saved-point",
  savedLabel: "saved-label",
  stateMask: "state-mask",
  countyMask: "county-mask",
  townshipMask: "township-mask",
  focusStateLine: "focus-state-line",
  focusCountyLine: "focus-county-line",
  focusTownshipLine: "focus-township-line",
} as const;

/** The area the user drilled into: everything outside it is hidden. */
export type MapFocus = {
  stateFips: string;
  statePostal: string;
  countyFips: string | null;
  /** Survey township at field scale: only its fields show. */
  township?: { plssid: string; bbox: BBox } | null;
};

const MATCH_NONE: FilterSpecification = ["==", ["get", "fips"], "__none__"];

/** Layer filters for a focus (null: no focus, nothing hidden). `null` as a value removes the filter. */
export function focusFilters(f: MapFocus | null): Record<string, FilterSpecification | null> {
  const county = f?.countyFips ?? null;
  const tw = f?.township ?? null;
  const inTownship: FilterSpecification | null = tw ? ["==", ["get", "plssid"], tw.plssid] : null;
  return {
    [LAYER.stateMask]: f ? ["!=", ["get", "fips"], f.stateFips] : MATCH_NONE,
    [LAYER.countyMask]: county ? ["!=", ["get", "fips"], county] : MATCH_NONE,
    [LAYER.townshipMask]: tw ? ["!=", ["get", "plssid"], tw.plssid] : MATCH_NONE,
    [LAYER.focusStateLine]: f ? ["==", ["get", "fips"], f.stateFips] : MATCH_NONE,
    [LAYER.focusCountyLine]: county ? ["==", ["get", "fips"], county] : MATCH_NONE,
    [LAYER.focusTownshipLine]: inTownship ?? MATCH_NONE,
    [LAYER.townshipsLine]: inTownship,
    // Outlines are drawn under the masks, but half the line width sticks out past a masked area.
    [LAYER.statesLine]: f ? ["==", ["get", "fips"], f.stateFips] : null,
    [LAYER.countiesLine]: !f ? null : county ? ["==", ["get", "fips"], county] : ["==", ["get", "state_fips"], f.stateFips],
    // A focused state is named in the breadcrumb; its centred name would cover a county name.
    [LAYER.stateLabels]: f ? MATCH_NONE : null,
    // A county name sits at the county's centre, usually outside the focused township.
    [LAYER.countyLabels]: tw
      ? MATCH_NONE
      : !f
        ? null
        : county
          ? ["==", ["get", "fips"], county]
          : ["==", ["get", "state_postal"], f.statePostal],
    // Towns carry no township: keep the ones inside its box (townships are near-squares).
    [LAYER.places]: tw
      ? ["within", bboxPolygon(tw.bbox)]
      : !f
        ? null
        : county
          ? ["==", ["get", "county_fips"], county]
          : ["==", ["get", "state_postal"], f.statePostal],
    // PLSS label points carry only their county: its first two digits are the state.
    [LAYER.townshipLabels]: inTownship ?? plssLabelFilter(f),
    [LAYER.sectionLabels]: plssLabelFilter(f),
  };
}

/** Layers that draw the survey townships at county scale. */
export const TOWNSHIP_LAYERS = [LAYER.townshipsFill, LAYER.townshipsLine, LAYER.townshipLabels] as const;

/**
 * Zoom from which townships show when they follow the focus: from ZOOM.township in a focused county,
 * otherwise only with the fields, so a view of several counties is not covered in townships.
 */
export function townshipMinZoom(focus: MapFocus | null, fieldMinZoom: number): number {
  return focus?.countyFips ? ZOOM.township : Math.max(ZOOM.township, fieldMinZoom);
}

function bboxPolygon([w, s, e, n]: BBox): GeoJSON.Polygon {
  return { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] };
}

function plssLabelFilter(f: MapFocus | null): FilterSpecification | null {
  if (!f) return null;
  if (f.countyFips) return ["==", ["get", "county_fips"], f.countyFips];
  return ["==", ["slice", ["get", "county_fips"], 0, 2], f.stateFips];
}

export const SOURCE = {
  boundaries: "boundaries",
  plss: "plss",
  fields: "fields",
  /** One label point per field, computed in FieldMap from the loaded field tiles. */
  fieldLabels: "field-labels",
  selection: "selection",
  focus: "focus",
  pin: "pin",
  saved: "saved",
} as const;

/** Zoom from which every field gets a crop and acres label. */
export const FIELD_LABEL_ZOOM = 14;

const FONT = { regular: ["Noto Sans Regular"], medium: ["Noto Sans Medium"] };

/** Absolute glyph URL template (MapLibre does not resolve relative ones). */
const glyphsUrl = () => {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return `${origin}${import.meta.env.BASE_URL}fonts/{fontstack}/{range}.pbf`;
};

/**
 * Revision of boundaries.pmtiles, sent as `?v=`. The API caches boundary tiles for a day, so bump
 * this whenever scripts/prepare_boundaries.py changes the layers, or browsers keep the old tiles.
 * 2: label point layers `state_labels`, `county_labels`, `places`.
 * 3: counties, county labels and towns only in the field states; towns from zoom 7.
 * 4: `places` get `county_fips` (county focus).
 * 5: `county_labels` from z5 (were z6), so a state that fits below zoom 6 (Illinois) shows county names.
 * 6: `state_labels` at the state's visual centre (Mercator centroid) instead of its widest part.
 */
export const BOUNDARY_TILES_REV = 6;

/**
 * County label text. Without a focus the state postal goes under the name at state scale (counties of
 * several states in view). In a focused state it says nothing new and doubles each label's height, so a
 * state with many counties (Illinois has 102) loses most names to collisions: name only.
 */
export function countyLabelText(stateFocused: boolean): ExpressionSpecification {
  if (stateFocused) return ["get", "name"];
  return [
    "step",
    ["zoom"],
    ["format", ["get", "name"], {}, "\n", {}, ["get", "state_postal"], { "font-scale": 0.8 }],
    9,
    ["get", "name"],
  ];
}

/** Revision of plss.pmtiles, sent as `?v=`. Bump when scripts/prepare_plss.py changes the layers. */
export const PLSS_TILES_REV = 1;

/**
 * Zoom bands from the contract: states < 7, counties 7 to 10, fields from field_tiles.min_zoom.
 * County lines, names and clicks start a bit earlier (5.5), so a focused state that fits at ~6
 * (Illinois is tall) already shows its counties.
 * Survey townships (6 x 6 miles) from 8, where a county fills the map; sections (1 mile) from 11.
 */
export const ZOOM = { countyLines: 5.5, county: 7, township: 8, sections: 11 } as const;

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
    fieldLine: token("--color-map-field-line", "#6f7c4f"),
    selected: token("--color-map-field-selected", "#f0b93b"),
    outline: token("--color-map-outline", "#17211b"),
    pin: token("--color-wheat-500", "#e2a62b"),
    surface: token("--color-surface", "#fffdf8"),
    saved: token("--color-map-saved", "#8a5a00"),
    label: token("--color-map-label", "#17211b"),
    labelMuted: token("--color-map-label-muted", "#3d4a40"),
    halo: token("--color-map-label-halo", "#fffdf8"),
  };
  const halo = { "text-halo-color": c.halo, "text-halo-width": 1.5, "text-halo-blur": 0.5 };
  const hovered: ExpressionSpecification = ["boolean", ["feature-state", "hover"], false];
  const supported: ExpressionSpecification = ["in", ["get", "postal"], ["literal", [...input.supportedStates]]];

  const style: StyleSpecification = {
    version: 8,
    glyphs: glyphsUrl(),
    sources: {
      [SOURCE.boundaries]: {
        type: "vector",
        tiles: [`${apiUrl("/tiles/boundaries/{z}/{x}/{y}.mvt")}?v=${BOUNDARY_TILES_REV}`],
        minzoom: 0,
        maxzoom: 10,
        promoteId: { states: "fips", counties: "fips" },
      },
      [SOURCE.plss]: {
        type: "vector",
        tiles: [`${apiUrl("/tiles/plss/{z}/{x}/{y}.mvt")}?v=${PLSS_TILES_REV}`],
        minzoom: 7,
        maxzoom: 12,
        promoteId: { townships: "plssid" },
      },
      [SOURCE.selection]: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
      [SOURCE.focus]: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
      [SOURCE.pin]: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
      [SOURCE.saved]: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
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
        minzoom: ZOOM.countyLines,
        paint: {
          // No county hover at field scale: it would tint the ground between the fields.
          "fill-color": ["step", ["zoom"], ["case", hovered, c.stateFields, c.county], input.fieldMinZoom, c.county],
          "fill-opacity": ["interpolate", ["linear"], ["zoom"], ZOOM.countyLines, 0, ZOOM.county, 1],
        },
      },
      {
        id: LAYER.countiesLine,
        type: "line",
        source: SOURCE.boundaries,
        "source-layer": "counties",
        minzoom: ZOOM.countyLines,
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
      {
        // The user's saved fields: outline in the saved color, under the labels.
        id: LAYER.savedLine,
        type: "line",
        source: SOURCE.saved,
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "line-color": c.saved, "line-width": ["interpolate", ["linear"], ["zoom"], 8, 1.5, 14, 3] },
      },
      {
        id: LAYER.savedPoint,
        type: "circle",
        source: SOURCE.saved,
        filter: ["==", ["geometry-type"], "Point"],
        paint: { "circle-radius": 6, "circle-color": c.surface, "circle-stroke-color": c.saved, "circle-stroke-width": 3 },
      },
      // Labels. Layers higher in the list win collisions, so the order is: counties, towns, states,
      // fields, saved fields (the most specific to the user last).
      {
        id: LAYER.countyLabels,
        type: "symbol",
        source: SOURCE.boundaries,
        "source-layer": "county_labels",
        // Same zoom as the county lines (countiesLine).
        minzoom: ZOOM.countyLines,
        maxzoom: 13,
        layout: {
          // FieldMap swaps it for the focus (countyLabelText).
          "text-field": countyLabelText(false),
          "text-font": FONT.regular,
          // A state view puts ~100 county names in 40-70 px wide counties (Illinois fits at ~5.9). To fit
          // most: mixed case (narrower) until towns show, no spacing, two-word names on two lines,
          // and a label may shift up or down to clear its neighbour (not sideways: it would leave its
          // county). From field scale, where towns show, spaced capitals so county names do not read as towns.
          "text-transform": ["step", ["zoom"], "none", input.fieldMinZoom, "uppercase"],
          "text-letter-spacing": ["step", ["zoom"], 0, input.fieldMinZoom, 0.08],
          "text-size": ["interpolate", ["linear"], ["zoom"], 5.5, 9, 10, 12],
          "text-max-width": 5,
          "text-line-height": 1.1,
          "text-variable-anchor": ["center", "top", "bottom"],
          "text-justify": "center",
          "text-padding": 0,
        },
        paint: { "text-color": c.labelMuted, ...halo },
      },
      {
        // Civil name ("Grant Twp") and survey label ("T84N R23W"), until the fields show.
        id: LAYER.townshipLabels,
        type: "symbol",
        source: SOURCE.plss,
        "source-layer": "township_labels",
        minzoom: ZOOM.township,
        maxzoom: input.fieldMinZoom,
        layout: {
          // Name only while townships are small on screen, then name over survey label.
          "text-field": [
            "step",
            ["zoom"],
            ["case", ["==", ["get", "name"], ""], ["get", "label"], ["get", "name"]],
            10,
            [
              "case",
              ["==", ["get", "name"], ""],
              ["get", "label"],
              ["format", ["get", "name"], {}, "\n", {}, ["get", "label"], { "font-scale": 0.8 }],
            ],
          ],
          "text-font": FONT.regular,
          "text-size": ["interpolate", ["linear"], ["zoom"], ZOOM.township, 9.5, 11, 11.5],
          "text-max-width": 6,
          "text-padding": 2,
        },
        paint: { "text-color": c.labelMuted, ...halo },
      },
      {
        // Section numbers 1 to 36, with the fields: stays under the field labels and the focus masks
        // (not a place label), so field and town labels win collisions.
        id: LAYER.sectionLabels,
        type: "symbol",
        source: SOURCE.plss,
        "source-layer": "section_labels",
        minzoom: ZOOM.sections,
        layout: {
          "text-field": ["to-string", ["get", "n"]],
          "text-font": FONT.medium,
          "text-size": ["interpolate", ["linear"], ["zoom"], ZOOM.sections, 10, 14, 14],
          "text-padding": 2,
        },
        paint: { "text-color": c.labelMuted, ...halo },
      },
      {
        id: LAYER.places,
        type: "symbol",
        source: SOURCE.boundaries,
        "source-layer": "places",
        // Towns only at township level (field scale), where they help find a field.
        minzoom: input.fieldMinZoom,
        layout: {
          "text-field": ["get", "name"],
          "text-font": FONT.regular,
          "text-size": ["step", ["get", "population"], 11, 25_000, 12, 100_000, 13.5, 500_000, 15],
          // Bigger towns are placed first and win collisions.
          "symbol-sort-key": ["-", 0, ["get", "population"]],
          "text-max-width": 8,
          "text-padding": 3,
        },
        paint: { "text-color": c.label, ...halo },
      },
      {
        id: LAYER.stateLabels,
        type: "symbol",
        source: SOURCE.boundaries,
        "source-layer": "state_labels",
        maxzoom: 8,
        layout: {
          "text-field": ["step", ["zoom"], ["get", "postal"], 4, ["get", "name"]],
          "text-font": FONT.medium,
          "text-size": ["interpolate", ["linear"], ["zoom"], 3, 11, 7, 17],
          "text-letter-spacing": 0.04,
          "text-max-width": 7,
          // States are few: always show them, even over town labels.
          "text-allow-overlap": true,
          "text-ignore-placement": true,
        },
        paint: {
          "text-color": ["case", supported, c.label, c.labelMuted],
          ...halo,
          "text-opacity": ["interpolate", ["linear"], ["zoom"], 7, 1, 8, 0],
        },
      },
      {
        id: LAYER.savedLabel,
        type: "symbol",
        source: SOURCE.saved,
        layout: {
          "text-field": ["get", "name"],
          "text-font": FONT.medium,
          "text-size": 13,
          "text-max-width": 10,
          // Points get the label beside the marker; polygons in the middle of the outline.
          "text-variable-anchor": ["top", "bottom", "left", "right"],
          "text-radial-offset": ["case", ["==", ["geometry-type"], "Point"], 1, 0],
        },
        paint: { "text-color": c.saved, ...halo },
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
        // Colored by latest crop group (crops.ts). Hover never changes the fill: only the outline
        // of the hovered field gets heavier (fieldsLine).
        id: LAYER.fieldsFill,
        type: "fill",
        source: SOURCE.fields,
        "source-layer": "fields",
        minzoom: input.fieldMinZoom,
        paint: {
          "fill-color": cropColorExpression((g) => token(g.token, g.fallback)),
          "fill-opacity": 0.85,
        },
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
    // Field labels: crop and acres, from zoom 14 and only where they fit. Under the saved labels.
    // Not drawn from the polygon tiles: MapLibre would label every tile piece of a field, so a field
    // across a tile edge got two or four labels. FieldMap puts one point per field in this source.
    style.sources[SOURCE.fieldLabels] = { type: "geojson", data: { type: "FeatureCollection", features: [] } };
    const labelAt = style.layers.findIndex((l) => l.id === LAYER.savedLabel);
    style.layers.splice(labelAt, 0, {
      id: LAYER.fieldsLabel,
      type: "symbol",
      source: SOURCE.fieldLabels,
      minzoom: Math.max(FIELD_LABEL_ZOOM, input.fieldMinZoom),
      layout: {
        "text-field": [
          "format",
          ["case", ["==", ["get", "crop_class"], ""], "Unknown crop", ["get", "crop_class"]],
          {},
          "\n",
          {},
          ["case", ["has", "acres"], ["concat", ["to-string", ["get", "acres"]], " ac"], ""],
          { "font-scale": 0.85 },
        ],
        "text-font": FONT.regular,
        "text-size": 12,
        "text-max-width": 7,
        "text-padding": 2,
      },
      paint: { "text-color": c.label, ...halo },
    });
  }
  // Survey townships and sections: above the fields (section lines often run along field edges), under
  // the selection. The township fill is invisible: it is there for hover and clicks at county scale.
  const plssLayers: StyleSpecification["layers"] = [
    {
      id: LAYER.townshipsFill,
      type: "fill",
      source: SOURCE.plss,
      "source-layer": "townships",
      minzoom: ZOOM.township,
      paint: {
        "fill-color": c.stateFields,
        // No hover at field scale, like the counties.
        "fill-opacity": ["step", ["zoom"], ["case", hovered, 0.7, 0], input.fieldMinZoom, 0],
      },
    },
    {
      id: LAYER.sectionsLine,
      type: "line",
      source: SOURCE.plss,
      "source-layer": "sections",
      minzoom: ZOOM.sections,
      paint: { "line-color": c.labelMuted, "line-opacity": 0.45, "line-width": 0.75, "line-dasharray": [2, 2] },
    },
    {
      id: LAYER.townshipsLine,
      type: "line",
      source: SOURCE.plss,
      "source-layer": "townships",
      minzoom: ZOOM.township,
      paint: {
        "line-color": c.regionLine,
        "line-width": ["interpolate", ["linear"], ["zoom"], ZOOM.township, 0.6, 12, 1.5],
        "line-dasharray": [3, 2],
      },
    },
  ];
  const plssAt = style.layers.findIndex((l) => l.id === LAYER.focusLine);
  style.layers.splice(plssAt, 0, ...plssLayers);
  // Focus masks and outlines go above fields, field labels and saved outlines, under the place labels.
  // The saved field names stay on top: they are the user's own and win label collisions.
  const noFocus = focusFilters(null);
  const masks: StyleSpecification["layers"] = [
    {
      id: LAYER.stateMask,
      type: "fill",
      source: SOURCE.boundaries,
      "source-layer": "states",
      filter: noFocus[LAYER.stateMask]!,
      paint: { "fill-color": c.ground },
    },
    {
      id: LAYER.countyMask,
      type: "fill",
      source: SOURCE.boundaries,
      "source-layer": "counties",
      filter: noFocus[LAYER.countyMask]!,
      paint: { "fill-color": c.ground },
    },
    {
      id: LAYER.townshipMask,
      type: "fill",
      source: SOURCE.plss,
      "source-layer": "townships",
      filter: noFocus[LAYER.townshipMask]!,
      paint: { "fill-color": c.ground },
    },
    {
      id: LAYER.focusStateLine,
      type: "line",
      source: SOURCE.boundaries,
      "source-layer": "states",
      filter: noFocus[LAYER.focusStateLine]!,
      paint: { "line-color": c.regionLine, "line-width": 2 },
    },
    {
      id: LAYER.focusCountyLine,
      type: "line",
      source: SOURCE.boundaries,
      "source-layer": "counties",
      filter: noFocus[LAYER.focusCountyLine]!,
      paint: { "line-color": c.outline, "line-width": 1.5 },
    },
    {
      id: LAYER.focusTownshipLine,
      type: "line",
      source: SOURCE.plss,
      "source-layer": "townships",
      filter: noFocus[LAYER.focusTownshipLine]!,
      paint: { "line-color": c.outline, "line-width": 1.5 },
    },
  ];
  const placeLabels = new Set<string>([
    LAYER.countyLabels,
    LAYER.townshipLabels,
    LAYER.places,
    LAYER.stateLabels,
  ]);
  const savedLabel = style.layers.filter((l) => l.id === LAYER.savedLabel);
  style.layers = [
    ...style.layers.filter((l) => !placeLabels.has(l.id) && l.id !== LAYER.savedLabel),
    ...masks,
    ...style.layers.filter((l) => placeLabels.has(l.id)),
    ...savedLabel,
  ];
  return style;
}
