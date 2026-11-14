import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { areaText, coordsText, selectionSearch, useField } from "@/entities/field";
import { CONUS_BBOX, mapConfigFrom, supportedStatesText, useCounty, useCoverage, useStates } from "@/entities/region";
import { friendlyMessage, type GeoState } from "@/shared/api";
import { fieldPath, ROUTES } from "@/shared/config";
import type { BBox } from "@/shared/lib";
import { buttonClass } from "@/shared/ui/button";
import { Skeleton } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { FieldMap, type FieldMapHandle, type MapHit, type MapStateHit } from "@/shared/ui/map";
import {
  MapBottomBar,
  MapCard,
  MapHint,
  MapLegend,
  MapScaleSteps,
  MapStage,
  MapTopBar,
  MapZoomControls,
  type LegendItem,
} from "@/shared/ui/map-overlay";
import s from "./explore-map.module.css";

const STAGE_NAMES = ["Country", "State", "County", "Field"] as const;
type Stage = 0 | 1 | 2 | 3;

/** Zoom bands. Fields start at coverage.field_tiles.min_zoom. Between county and field there is no API unit. */
const stageOf = (zoom: number, fieldMinZoom: number): Stage =>
  zoom >= fieldMinZoom ? 3 : zoom >= 7 ? 2 : zoom >= 5 ? 1 : 0;

const legendFor = (stage: Stage, covered: boolean): { title: string; items: LegendItem[]; note: string } => {
  const line = "var(--color-map-region-line)";
  switch (stage) {
    case 0:
      return {
        title: "States",
        items: [
          { label: "Field outlines available", fill: "var(--color-map-state-fields)", line },
          { label: "Point analysis only", fill: "var(--color-map-state)", line },
        ],
        note: "Field outlines are hidden at this scale. Zoom to a county to see them.",
      };
    case 1:
      return {
        title: "Counties",
        items: [{ label: "County", fill: "var(--color-map-county)", line }],
        note: covered ? "Click a county to zoom to it." : "No field outlines in this state yet.",
      };
    case 2:
      return {
        title: "Counties",
        items: [{ label: "County", fill: "var(--color-map-county)", line }],
        note: "Estimated field areas appear as you zoom in further.",
      };
    default:
      return {
        title: "Fields",
        items: [
          { label: "Estimated field area", fill: "var(--color-map-field-1)", line: "var(--color-map-field-line)" },
          { label: "Selected", fill: "var(--color-map-field-selected)", line: "var(--color-map-outline)" },
        ],
        note: "Estimated from USDA crop maps. Not a legal or ownership boundary.",
      };
  }
};

/**
 * Landing map: country, state, county, then estimated field areas (zoom 12+ from the PMTiles file).
 * Clicking a field calls GET /fields/{id} and offers "Open field".
 */
export function ExploreMap() {
  const coverage = useCoverage();
  const states = useStates();
  const config = useMemo(() => mapConfigFrom(coverage.data), [coverage.data]);
  const mapRef = useRef<FieldMapHandle>(null);

  const [zoom, setZoom] = useState(3);
  const [focusState, setFocusState] = useState<MapStateHit | null>(null);
  const [countyFips, setCountyFips] = useState<string | null>(null);
  const [hoverName, setHoverName] = useState<{ name: string; supported: boolean } | null>(null);
  const [fieldId, setFieldId] = useState<string | null>(null);
  const [noCoverageIn, setNoCoverageIn] = useState<string | null>(null);

  const county = useCounty(countyFips);
  const field = useField(fieldId);
  const stage = stageOf(zoom, config.fieldMinZoom);
  const supported = useCallback((postal: string) => config.supportedStates.includes(postal), [config.supportedStates]);
  const stateCovered = focusState ? supported(focusState.postal) : true;

  // Fit the map to the supported states once coverage arrives.
  const fittedOnce = useRef(false);
  useEffect(() => {
    if (coverage.data && !fittedOnce.current) {
      fittedOnce.current = true;
      mapRef.current?.fitBBox(coverage.data.bounds as BBox);
    }
  }, [coverage.data]);

  // Zoom to a county once its bbox loads.
  useEffect(() => {
    if (county.data) mapRef.current?.fitBBox(county.data.bbox as BBox, config.fieldMinZoom - 0.5);
  }, [county.data, config.fieldMinZoom]);

  const goState = (st: GeoState) => {
    setFocusState({ fips: st.fips, name: st.name, postal: st.postal });
    setCountyFips(null);
    setFieldId(null);
    setNoCoverageIn(null);
    mapRef.current?.fitBBox(st.bbox as BBox);
  };

  const reset = () => {
    setFocusState(null);
    setCountyFips(null);
    setFieldId(null);
    setNoCoverageIn(null);
    mapRef.current?.fitBBox((coverage.data?.bounds as BBox | undefined) ?? CONUS_BBOX);
  };

  const onClick = (hit: MapHit) => {
    setNoCoverageIn(null);
    if (stage === 3) {
      setFieldId(hit.field ? hit.field.field_id : null);
      return;
    }
    if (stage === 2) {
      // Between county and field there is no API unit: zoom in where the user clicked.
      mapRef.current?.flyTo(hit.point, config.fieldMinZoom + 0.5);
      return;
    }
    if (hit.county && hit.zoom >= 6) {
      setCountyFips(hit.county.fips);
      return;
    }
    if (hit.state) {
      setFocusState(hit.state);
      setCountyFips(null);
      const known = states.data?.find((st) => st.fips === hit.state!.fips);
      if (known) mapRef.current?.fitBBox(known.bbox as BBox);
      else {
        setNoCoverageIn(hit.state.name);
        mapRef.current?.flyTo(hit.point, 6);
      }
      return;
    }
    if (stage < 2) mapRef.current?.flyTo(hit.point, Math.min(zoom + 2, 8));
  };

  const onHover = (hit: MapHit | null) => {
    const st = hit?.state;
    setHoverName(st ? { name: st.name, supported: supported(st.postal) } : null);
  };

  const legend = legendFor(stage, stateCovered);
  const hint = [
    hoverName
      ? `${hoverName.name}: click to zoom in${hoverName.supported ? "" : ". Point analysis only"}`
      : "Click a state to zoom in",
    stateCovered ? "Click a county, or use + to zoom in" : "No field outlines here yet. Use Pick a field for a point",
    "Click where your field is to zoom in",
    fieldId ? "Selected. Open it to see base conditions" : "Click an estimated field area to select it",
  ][stage];

  const crumbs: { label: string; onClick: () => void }[] = [{ label: "United States", onClick: reset }];
  if (focusState && stage >= 1) {
    const st = states.data?.find((x) => x.fips === focusState.fips);
    crumbs.push({ label: focusState.name, onClick: () => (st ? goState(st) : mapRef.current?.flyTo(mapCenter(), 6)) });
  }
  if (county.data && stage >= 2) {
    crumbs.push({
      label: `${county.data.name} County`,
      onClick: () => {
        setFieldId(null);
        mapRef.current?.fitBBox(county.data!.bbox as BBox, config.fieldMinZoom - 0.5);
      },
    });
  }

  const selectionShape = field.data
    ? { coordinates: field.data.geometry.coordinates, buffered: field.data.resolved_by === "buffered_point" }
    : null;

  return (
    <MapStage height={720}>
      <FieldMap
        ref={mapRef}
        config={config}
        initialBBox={CONUS_BBOX}
        selection={selectionShape}
        pin={null}
        ariaLabel="Map of the contiguous United States. Zoom from states to counties and estimated field areas."
        onClick={onClick}
        onHover={onHover}
        onZoomEnd={setZoom}
      />

      <MapTopBar>
        <nav aria-label="Map scale" className={s.crumbs}>
          <ol className={s.crumbList}>
            {crumbs.map((c, i) => (
              <li key={c.label} className={s.crumbItem}>
                {i > 0 && <Icon name="chevron" size={16} />}
                <button
                  type="button"
                  className={s.crumb}
                  onClick={c.onClick}
                  aria-current={i === crumbs.length - 1 ? "location" : undefined}
                >
                  {c.label}
                </button>
              </li>
            ))}
          </ol>
        </nav>
        <div className={s.jump}>
          <label htmlFor="map-jump" className={s.jumpLabel}>
            Jump to
          </label>
          <select
            id="map-jump"
            className={s.jumpSelect}
            value={focusState?.fips ?? ""}
            onChange={(e) => {
              const st = states.data?.find((x) => x.fips === e.target.value);
              if (st) goState(st);
              else reset();
            }}
          >
            <option value="">State…</option>
            {states.data?.map((st) => (
              <option key={st.fips} value={st.fips}>
                {st.name}
              </option>
            ))}
          </select>
        </div>
      </MapTopBar>

      <MapZoomControls
        onZoomIn={() => mapRef.current?.zoomIn()}
        onZoomOut={() => mapRef.current?.zoomOut()}
        onReset={reset}
        resetLabel="Show the whole country"
      >
        <MapScaleSteps steps={4} current={stage} label={`Map scale: ${STAGE_NAMES[stage]}`} />
      </MapZoomControls>

      <MapBottomBar>
        <MapLegend title={legend.title} items={legend.items} note={legend.note} />
        <MapHint>{coverage.isError ? friendlyMessage(coverage.error) : hint}</MapHint>

        {noCoverageIn && (
          <MapCard label={`No field outlines in ${noCoverageIn}`}>
            <div className={s.cardTitleSmall}>No field outlines in {noCoverageIn} yet</div>
            <p className={s.muted}>
              Estimated field areas cover {supportedStatesText(coverage.data)} for now. You can still analyze any point in
              the contiguous US.
            </p>
            <Link to={ROUTES.pickField} className={s.strongLink}>
              Pick a point instead
            </Link>
          </MapCard>
        )}

        {fieldId && (
          <MapCard label="Selected estimated field area">
            <div className={s.cardHead}>
              <div className={s.cardTitle}>Estimated field area</div>
              <button type="button" className={s.close} onClick={() => setFieldId(null)} aria-label="Clear selected field">
                <Icon name="close" size={18} />
              </button>
            </div>
            {field.isPending && (
              <div className={s.cardBody} role="status">
                <Skeleton height={16} width="60%" />
                <Skeleton height={16} width="80%" />
                <span className="visually-hidden">Loading the field</span>
              </div>
            )}
            {field.isError && (
              <p className={s.error} role="alert">
                {friendlyMessage(field.error)}
              </p>
            )}
            {field.data && (
              <>
                <div className={s.cardBody}>
                  {areaText(field.data) && <span>About {areaText(field.data)}</span>}
                  {field.data.field_id && <span className={s.mono12}>{field.data.field_id}</span>}
                  <span className={s.mono13}>{coordsText(field.data)}</span>
                </div>
                <Link
                  to={fieldPath(selectionSearch(field.data))}
                  className={buttonClass({ variant: "primary", size: "md", block: true, className: s.open })}
                >
                  Open field
                  <Icon name="arrow-right" size={18} />
                </Link>
                <p className={s.fine}>
                  Opening it sends this location to our server to read NASA and soil data for the field. The outline is
                  an estimate, not a legal boundary.
                </p>
              </>
            )}
          </MapCard>
        )}
      </MapBottomBar>
    </MapStage>
  );

  function mapCenter() {
    return { lat: 39.8, lon: -96 };
  }
}
