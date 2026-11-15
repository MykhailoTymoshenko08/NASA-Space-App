import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { areaText, coordsText, selectionSearch, useField } from "@/entities/field";
import {
  CONUS_BBOX,
  mapConfigFrom,
  stateBBox,
  supportedStatesText,
  useCounty,
  useCoverage,
  useStates,
} from "@/entities/region";
import { useSavedFieldShapes } from "@/entities/saved-field";
import { useSession } from "@/entities/session";
import { friendlyMessage, type GeoState } from "@/shared/api";
import { fieldPath, ROUTES } from "@/shared/config";
import type { BBox } from "@/shared/lib";
import { buttonClass } from "@/shared/ui/button";
import { Skeleton } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import {
  COUNTY_FIT_MIN_ZOOM,
  FieldMap,
  focusForView,
  isNarrowScreen,
  sameFocus,
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
  MapCard,
  MapHint,
  MapLegend,
  MapScaleSteps,
  MapStage,
  MapTopBar,
  MapZoomControls,
  SAVED_LEGEND_ITEM,
  SECTION_LEGEND_ITEM,
  TOWNSHIP_LEGEND_ITEM,
  type LegendItem,
} from "@/shared/ui/map-overlay";
import s from "./explore-map.module.css";

const STAGE_NAMES = ["Country", "State", "County", "Field"] as const;
type Stage = 0 | 1 | 2 | 3;

/**
 * Zoom bands. Fields start at coverage.field_tiles.min_zoom. Between county and field, the county scale
 * shows survey townships (from ZOOM.township): a click on one goes to its fields.
 */
const stageOf = (zoom: number, fieldMinZoom: number): Stage =>
  zoom >= fieldMinZoom ? 3 : zoom >= 7 ? 2 : zoom >= 5 ? 1 : 0;

const legendFor = (
  stage: Stage,
  covered: boolean,
  hasSaved: boolean,
  countyFocused: boolean,
): { title: string; items: LegendItem[]; note: string } => {
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
        note: covered ? "Click a county to see its townships." : "No field outlines in this state yet.",
      };
    case 2:
      // Townships are drawn only in the focused county (FieldMap townshipsFollowFocus).
      if (!countyFocused)
        return {
          title: "Counties",
          items: [{ label: "County", fill: "var(--color-map-county)", line }],
          note: "Click a county to see its townships.",
        };
      return {
        title: "Counties and townships",
        items: [{ label: "County", fill: "var(--color-map-county)", line }, TOWNSHIP_LEGEND_ITEM],
        note: "Townships are the survey squares from your deed or plat book. Click yours to see its fields.",
      };
    default:
      return {
        title: "Fields by latest crop",
        items: [
          ...CROP_LEGEND_ITEMS,
          { label: "Selected", fill: "var(--color-map-field-selected)", line: "var(--color-map-outline)" },
          ...(hasSaved ? [SAVED_LEGEND_ITEM] : []),
          SECTION_LEGEND_ITEM,
        ],
        note: "Zoom in further to see each field's crop and acres. Estimated from USDA crop maps. Not a legal or ownership boundary.",
      };
  }
};

/**
 * Landing map: country, state, county, then estimated field areas (zoom 12+ from the PMTiles file).
 * Clicking a field calls GET /fields/{id} and offers "Open field".
 */
export function ExploreMap({ className }: { className?: string } = {}) {
  const coverage = useCoverage();
  const states = useStates();
  const config = useMemo(() => mapConfigFrom(coverage.data), [coverage.data]);
  const mapRef = useRef<FieldMapHandle>(null);
  // On a phone the whole country leaves each state a few dozen pixels wide, too small to tap: open on
  // the field states instead. Zooming out and "Show the whole country" still reach CONUS.
  const startBBox = useMemo(
    () => (isNarrowScreen() && coverage.data ? (coverage.data.bounds as BBox) : CONUS_BBOX),
    [coverage.data],
  );

  const [zoom, setZoom] = useState(3);
  const [focusState, setFocusState] = useState<MapStateHit | null>(null);
  const [countyFips, setCountyFips] = useState<string | null>(null);
  const [township, setTownship] = useState<MapTownshipHit | null>(null);
  const [hoverName, setHoverName] = useState<{ name: string; supported: boolean } | null>(null);
  const [fieldId, setFieldId] = useState<string | null>(null);
  const [noCoverageIn, setNoCoverageIn] = useState<string | null>(null);

  const session = useSession();
  const saved = useSavedFieldShapes(session.user?.id ?? null);
  const county = useCounty(countyFips);
  const field = useField(fieldId);
  const stage = stageOf(zoom, config.fieldMinZoom);
  const supported = useCallback((postal: string) => config.supportedStates.includes(postal), [config.supportedStates]);
  const stateCovered = focusState ? supported(focusState.postal) : true;

  // A county click fits the map to the county once its bbox arrives (the tiles carry no bbox).
  // If the county cannot be loaded, go straight to the fields where the user clicked, as before.
  const pendingCounty = useRef<{ fips: string; point: MapHit["point"] } | null>(null);
  useEffect(() => {
    const pending = pendingCounty.current;
    if (!pending || pending.fips !== countyFips) return;
    if (county.data?.fips === pending.fips) {
      pendingCounty.current = null;
      mapRef.current?.fitBBox(county.data.bbox as BBox, config.fieldMinZoom - 0.5, COUNTY_FIT_MIN_ZOOM);
    } else if (county.isError) {
      pendingCounty.current = null;
      mapRef.current?.flyTo(pending.point, config.fieldMinZoom + 0.5);
    }
  }, [county.data, county.isError, countyFips, config.fieldMinZoom]);

  /** A township fills the map, never further out than the fields' zoom. */
  const goTownship = (t: MapTownshipHit) => {
    setTownship(t);
    setFieldId(null);
    mapRef.current?.fitBBox(t.bbox, undefined, config.fieldMinZoom + 0.25);
  };

  // A phone, or a short desktop window (the landing map is one window tall), fits a tall state such as
  // Illinois below the zoom where counties show: zoom in to the counties instead (the state's edges may
  // be off screen, the next step is a county anyway).
  const fitState = (bbox: BBox) => mapRef.current?.fitBBox(bbox, undefined, ZOOM.countyLines);

  const goState = (st: GeoState) => {
    setFocusState({ fips: st.fips, name: st.name, postal: st.postal });
    setCountyFips(null);
    setTownship(null);
    pendingCounty.current = null;
    setFieldId(null);
    setNoCoverageIn(null);
    fitState(st.bbox as BBox);
  };

  const reset = () => {
    setFocusState(null);
    setCountyFips(null);
    setTownship(null);
    pendingCounty.current = null;
    setFieldId(null);
    setNoCoverageIn(null);
    mapRef.current?.fitBBox(CONUS_BBOX);
  };

  // Only the focused state (and county, and township) is shown. Zooming out past it brings the rest back.
  const focus: MapFocus | null = focusState
    ? {
        stateFips: focusState.fips,
        statePostal: focusState.postal,
        countyFips,
        // Ends below field scale (onZoomEnd clears the township).
        township: township ? { plssid: township.plssid, bbox: township.bbox } : null,
      }
    : null;

  // The map stays in the focused county, else state (shared/ui/map/FieldMap.tsx `bounds`). The breadcrumbs,
  // "Jump to" and clicks on the hidden land around it lead out.
  const bounds =
    (countyFips && county.data?.fips === countyFips ? (county.data.bbox as BBox) : null) ??
    (focusState ? stateBBox(focusState.fips) : null);

  /** Zoom below which a focus ends: one level under the zoom that fits the area. */
  const floorFor = (bbox: number[] | undefined, fallback: number) => {
    const z = bbox ? mapRef.current?.zoomForBBox(bbox as BBox) : null;
    return z != null ? z - 1 : fallback;
  };

  const onZoomEnd = (z: number) => {
    setZoom(z);
    // Fields are hidden below their zoom: the selection goes with them.
    if (z < config.fieldMinZoom) {
      setFieldId(null);
      setTownship(null);
    }
    if (countyFips && z < Math.min(floorFor(county.data?.bbox, 8), config.fieldMinZoom - 1)) setCountyFips(null);
    if (focusState && z < floorFor(states.data?.find((x) => x.fips === focusState.fips)?.bbox, 5)) {
      setFocusState(null);
      setCountyFips(null);
      setNoCoverageIn(null);
    }
  };

  // Moving the map focuses what is under its center, as a click would (shared/ui/map/view-focus.ts).
  const onViewChange = (view: MapView) => {
    // Our own camera moves follow a click, which already set the focus.
    if (!view.byUser || pendingCounty.current) return;
    const st = view.state ? states.data?.find((x) => x.fips === view.state!.fips) : undefined;
    const stateFitZoom = st ? (mapRef.current?.zoomForBBox(st.bbox as BBox) ?? null) : null;
    const cur = { state: focusState, countyFips, township };
    const next = focusForView(view, cur, { fieldMinZoom: config.fieldMinZoom, stateFitZoom, region: "follow" });
    if (sameFocus(next, cur)) return;
    if (next.state?.fips !== focusState?.fips) {
      setFocusState(next.state);
      setNoCoverageIn(null);
    }
    if (next.countyFips !== countyFips) setCountyFips(next.countyFips);
    if (next.township?.plssid !== township?.plssid) {
      setTownship(next.township);
      // The selected field may now be under the mask.
      setFieldId(null);
    }
  };

  const onClick = (rawHit: MapHit) => {
    setNoCoverageIn(null);
    // A click on a hidden area moves the focus there: a township at field scale, else its county or state.
    if (rawHit.outsideFocus && stage === 3) {
      if (rawHit.township) {
        if (rawHit.state) setFocusState(rawHit.state);
        if (rawHit.county) setCountyFips(rawHit.county.fips);
        pendingCounty.current = null;
        goTownship(rawHit.township);
      }
      return;
    }
    // Outside the focused county, go to the county first, not straight into one of its townships.
    const hit = rawHit.outsideFocus ? { ...rawHit, township: null } : rawHit;
    if (stage === 3) {
      setFieldId(hit.field ? hit.field.field_id : null);
      return;
    }
    // A click goes one level down. Township (county scale): its fields. The state and county are kept
    // for the focus and the breadcrumb.
    if (hit.township) {
      if (hit.state && focusState?.fips !== hit.state.fips) setFocusState(hit.state);
      if (hit.county) setCountyFips(hit.county.fips);
      pendingCounty.current = null;
      goTownship(hit.township);
      return;
    }
    // County: fit it, so its townships show. The focused county again (no township under the pointer,
    // e.g. a server without survey data): straight to its fields, where the user clicked.
    if (hit.county && hit.zoom >= ZOOM.countyLines) {
      if (hit.state && focusState?.fips !== hit.state.fips) setFocusState(hit.state);
      if (hit.county.fips === countyFips) {
        mapRef.current?.flyTo(hit.point, config.fieldMinZoom + 0.5);
        return;
      }
      setCountyFips(hit.county.fips);
      setTownship(null);
      pendingCounty.current = { fips: hit.county.fips, point: hit.point };
      return;
    }
    if (stage === 2) {
      mapRef.current?.flyTo(hit.point, config.fieldMinZoom + 0.5);
      return;
    }
    if (hit.state) {
      setFocusState(hit.state);
      setCountyFips(null);
      const known = states.data?.find((st) => st.fips === hit.state!.fips);
      if (known) fitState(known.bbox as BBox);
      else {
        setNoCoverageIn(hit.state.name);
        // Not a field state: no /geo/states entry, but the static box fits it like any other.
        const bbox = stateBBox(hit.state.fips);
        if (bbox) fitState(bbox);
        else mapRef.current?.flyTo(hit.point, 6);
      }
      return;
    }
    if (stage < 2) mapRef.current?.flyTo(hit.point, Math.min(zoom + 2, 8));
  };

  const onHover = (hit: MapHit | null) => {
    const st = hit?.state;
    setHoverName(st ? { name: st.name, supported: supported(st.postal) } : null);
  };

  const legend = legendFor(stage, stateCovered, saved.length > 0, countyFips !== null);
  const hint = [
    hoverName
      ? `${hoverName.name}: click to zoom in${hoverName.supported ? "" : ". Point analysis only"}`
      : "Click a state to zoom in",
    stateCovered ? "Click a county to see its townships" : "No field outlines here yet. Use Pick a field for a point",
    countyFips ? "Click your township to see its fields" : "Click a county to see its townships",
    fieldId ? "Selected. Open it to see base conditions" : "Click an estimated field area to select it",
  ][stage];

  // The country needs no name (the map shows it): the trail starts once the user is in a state, with a
  // way back to all of them.
  const crumbs: { label: string; onClick: () => void }[] = [{ label: "All states", onClick: reset }];
  if (focusState && stage >= 1) {
    const st = states.data?.find((x) => x.fips === focusState.fips);
    crumbs.push({ label: focusState.name, onClick: () => (st ? goState(st) : mapRef.current?.flyTo(mapCenter(), 6)) });
  }
  if (county.data && stage >= 2) {
    crumbs.push({
      label: `${county.data.name} County`,
      onClick: () => {
        setFieldId(null);
        setTownship(null);
        mapRef.current?.fitBBox(county.data!.bbox as BBox, config.fieldMinZoom - 0.5, COUNTY_FIT_MIN_ZOOM);
      },
    });
  }
  if (township && stage === 3) {
    const t = township;
    crumbs.push({ label: t.name ? `${t.name} (${t.label})` : t.label, onClick: () => goTownship(t) });
  }

  const selectionShape = field.data
    ? { coordinates: field.data.geometry.coordinates, buffered: field.data.resolved_by === "buffered_point" }
    : null;

  return (
    <MapStage height={720} className={className}>
      <FieldMap
        ref={mapRef}
        config={config}
        initialBBox={startBBox}
        selection={selectionShape}
        pin={null}
        saved={saved}
        focus={focus}
        townshipsFollowFocus
        outerBBox={CONUS_BBOX}
        bounds={bounds}
        pageScrollsOverMap
        ariaLabel="Map of the contiguous United States. Zoom from states to counties and estimated field areas."
        onClick={onClick}
        onHover={onHover}
        onZoomEnd={onZoomEnd}
        onViewChange={onViewChange}
      />

      <MapTopBar>
        {crumbs.length > 1 && (
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
        )}
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
