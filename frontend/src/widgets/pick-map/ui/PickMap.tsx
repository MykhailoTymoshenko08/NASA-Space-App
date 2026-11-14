import { useEffect, useMemo, useRef, useState } from "react";
import { fetchField, isBuffered, resolveFieldAt } from "@/entities/field";
import { CONUS_BBOX, mapConfigFrom, useCoverage } from "@/entities/region";
import { friendlyMessage, type County, type FieldSelection, type SelectionSource } from "@/shared/api";
import { bboxOfRing, type BBox, type LatLon } from "@/shared/lib";
import { Icon } from "@/shared/ui/icon";
import { FieldMap, type FieldMapHandle, type MapHit } from "@/shared/ui/map";
import { MapBottomBar, MapEmpty, MapHint, MapLegend, MapStage, MapZoomControls, type LegendItem } from "@/shared/ui/map-overlay";
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
 */
export function PickMap({ county, pin, selection, placeLabel, onSelect }: Props) {
  const coverage = useCoverage();
  const config = useMemo(() => mapConfigFrom(coverage.data), [coverage.data]);
  const mapRef = useRef<FieldMapHandle>(null);
  const [zoom, setZoom] = useState(4);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fieldScale = zoom >= config.fieldMinZoom;
  const hasPlace = county !== null || selection !== null || pin !== null;

  useEffect(() => {
    if (county) mapRef.current?.fitBBox(county.bbox as BBox, config.fieldMinZoom - 1);
  }, [county, config.fieldMinZoom]);

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
    if (hit.zoom < config.fieldMinZoom) {
      mapRef.current?.flyTo(hit.point, config.fieldMinZoom + 0.5);
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
        { label: "Estimated field area", fill: "var(--color-map-field-1)", line: "var(--color-map-field-line)" },
        { label: buffered ? "Circle around your point" : "Selected", fill: "var(--color-map-field-selected)", line: "var(--color-map-outline)" },
      ]
    : [{ label: "County", fill: "var(--color-map-county)", line }];

  const hint = error
    ? error
    : busy
      ? "Finding the field…"
      : !fieldScale
        ? "Click where your field is to zoom in"
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
          ariaLabel={hasPlace ? `Map of ${title}` : "Map"}
          onClick={onClick}
          onZoomEnd={setZoom}
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
