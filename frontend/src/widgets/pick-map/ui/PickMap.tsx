import { useEffect, useMemo, useRef, useState } from "react";
import { fetchField, isBuffered, resolveFieldAt } from "@/entities/field";
import { CONUS_BBOX, mapConfigFrom, useCoverage } from "@/entities/region";
import { useSavedFieldShapes } from "@/entities/saved-field";
import { useSession } from "@/entities/session";
import { friendlyMessage, type County, type FieldSelection, type SelectionSource } from "@/shared/api";
import { bboxOfRing, type BBox, type LatLon } from "@/shared/lib";
import { Icon } from "@/shared/ui/icon";
import {
  FieldMap,
  focusForView,
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
  MapEmpty,
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

type Props = {
  /** County chosen in the county picker; the map jumps to it. */
  county: County | null;
  /** Point from a pasted link or coordinates; shown as a pin. */
  pin: LatLon | null;
  /** Current selection; drawn on the map and the map fits to it. */
  selection: FieldSelection | null;
  /** Shown in the bar when there is no county (e.g. the pasted point). */
  placeLabel: string | null;
  onSelect: (selection: FieldSelection) => void;
};

/**
 * Pick-a-field map. Zoom into the county, then click an estimated field area:
 * a field feature calls GET /fields/{id}; any other click calls POST /fields/resolve (snap or circle).
 * Focus: the county the user entered hides every other county. At field scale, the survey township under
 * the map center hides every other township (shared/ui/map/view-focus.ts), inside the entered county.
 */
export function PickMap({ county, pin, selection, placeLabel, onSelect }: Props) {
  const coverage = useCoverage();
  const config = useMemo(() => mapConfigFrom(coverage.data), [coverage.data]);
  const mapRef = useRef<FieldMapHandle>(null);
  const session = useSession();
  const saved = useSavedFieldShapes(session.user?.id ?? null);
  const [zoom, setZoom] = useState(4);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Focused township at field scale, with its state (the focus needs one when no county was entered). */
  const [area, setArea] = useState<{ state: MapStateHit | null; township: MapTownshipHit } | null>(null);
  const fieldScale = zoom >= config.fieldMinZoom;
  const hasPlace = county !== null || selection !== null || pin !== null;

  useEffect(() => {
    setArea(null);
    if (county) mapRef.current?.fitBBox(county.bbox as BBox, config.fieldMinZoom - 1);
  }, [county, config.fieldMinZoom]);

  const tw = area ? { plssid: area.township.plssid, bbox: area.township.bbox } : null;
  const focus: MapFocus | null = county
    ? { stateFips: county.state_fips, statePostal: county.state_postal, countyFips: county.fips, township: tw }
    : area?.state
      ? { stateFips: area.state.fips, statePostal: area.state.postal, countyFips: null, township: tw }
      : null;

  // Every move counts here, ours too: fitting a selection or a pasted point focuses its township.
  const onViewChange = (view: MapView) => {
    const cur = { state: null, countyFips: county?.fips ?? null, township: area?.township ?? null };
    const next = focusForView(view, cur, { fieldMinZoom: config.fieldMinZoom, stateFitZoom: null, region: "fixed" });
    if (next.township?.plssid === area?.township.plssid) return;
    setArea(next.township ? { state: view.state, township: next.township } : null);
  };

  useEffect(() => {
    const ring = selection?.geometry.coordinates[0];
    if (ring && ring.length > 0) {
      const b = selection?.bbox ?? bboxOfRing(ring);
      mapRef.current?.fitBBox(b as BBox, 16);
    } else if (pin) {
      mapRef.current?.flyTo(pin, config.fieldMinZoom + 1);
    }
  }, [selection, pin, config.fieldMinZoom]);

  const pick = async (load: () => Promise<FieldSelection>) => {
    setBusy(true);
    setError(null);
    try {
      onSelect(await load());
    } catch (err) {
      setError(friendlyMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const onClick = (hit: MapHit) => {
    setError(null);
    if (hit.outsideFocus) {
      // The county is what the user entered: other counties are reached by changing it.
      if (county && hit.county?.fips !== county.fips) {
        setError(`That is outside ${county.name} County. Choose another county to go there.`);
        return;
      }
      // Another township: focus it.
      if (hit.township) {
        setArea({ state: hit.state, township: hit.township });
        mapRef.current?.fitBBox(hit.township.bbox, undefined, config.fieldMinZoom + 0.25);
      }
      return;
    }
    if (hit.zoom < config.fieldMinZoom) {
      // A township (survey square) fills the map; anywhere else, zoom in where the user clicked.
      if (hit.township) mapRef.current?.fitBBox(hit.township.bbox, undefined, config.fieldMinZoom + 0.25);
      else mapRef.current?.flyTo(hit.point, config.fieldMinZoom + 0.5);
      return;
    }
    const source: SelectionSource = "map_click";
    if (hit.field?.field_id) void pick(() => fetchField(hit.field!.field_id));
    else void pick(() => resolveFieldAt(hit.point, source));
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
    : [{ label: "County", fill: "var(--color-map-county)", line }, TOWNSHIP_LEGEND_ITEM];

  const hint = error
    ? error
    : busy
      ? "Finding the field…"
      : !fieldScale
        ? "Click your township, or where your field is, to zoom in"
        : buffered
          ? "No field outlines here. We use a circle around your point"
          : selection
            ? "Selected. Check it on the left"
            : "Click an estimated field area to select it";

  const title = county ? `${county.name} County, ${county.state_postal}` : (placeLabel ?? "No location yet");
  const scaleText = !hasPlace
    ? "Add a county, a link or coordinates"
    : fieldScale
      ? "Field scale. Outlines are estimates from USDA crop maps."
      : "County scale. Zoom in to see estimated field areas.";

  return (
    <MapStage height={700}>
      <div className={s.bar}>
        <div className={s.barText}>
          <div className={s.place}>{title}</div>
          <div className={s.scale}>{scaleText}</div>
        </div>
        {county && fieldScale && (
          <button
            type="button"
            className={s.back}
            onClick={() => mapRef.current?.fitBBox(county.bbox as BBox, config.fieldMinZoom - 1)}
          >
            <Icon name="arrow-left" size={18} />
            Back to county
          </button>
        )}
      </div>
      <div className={s.mapArea}>
        <FieldMap
          ref={mapRef}
          config={config}
          initialBBox={(coverage.data?.bounds as BBox | undefined) ?? CONUS_BBOX}
          selection={selection ? { coordinates: selection.geometry.coordinates, buffered } : null}
          pin={pin}
          saved={saved}
          focus={focus}
          townshipsFollowFocus
          outerBBox={CONUS_BBOX}
          ariaLabel={hasPlace ? `Map of ${title}` : "Map"}
          onClick={onClick}
          onZoomEnd={setZoom}
          onViewChange={onViewChange}
        />
        {!hasPlace && <MapEmpty>Your map appears here once we have a location.</MapEmpty>}
        {hasPlace && (
          <>
            <MapZoomControls
              onZoomIn={() => mapRef.current?.zoomIn()}
              onZoomOut={() => mapRef.current?.zoomOut()}
              onReset={() =>
                county
                  ? mapRef.current?.fitBBox(county.bbox as BBox, config.fieldMinZoom - 1)
                  : selection && mapRef.current?.fitBBox((selection.bbox ?? bboxOfRing(selection.geometry.coordinates[0] ?? [])) as BBox, 16)
              }
              resetLabel="Show the whole county"
            />
            <MapBottomBar>
              <MapLegend items={legend} />
              <MapHint>{hint}</MapHint>
            </MapBottomBar>
          </>
        )}
      </div>
    </MapStage>
  );
}
