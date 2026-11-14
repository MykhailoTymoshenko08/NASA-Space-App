import type { FieldSelection, SelectionRef } from "@/shared/api";
import { formatAreaBoth, formatLatLon, metersToFeet, type LatLon } from "@/shared/lib";
import { buildFieldSearch } from "./field-url";

/**
 * Words for a resolved selection. The contract requires "estimated field area" and
 * never implying a legal or ownership boundary.
 */
export const isBuffered = (sel: FieldSelection) => sel.resolved_by === "buffered_point";

export const fieldKind = (sel: FieldSelection) => (isBuffered(sel) ? "Circle around your point" : "Estimated field area");

export const countyLine = (sel: FieldSelection) => `${sel.county.name} County, ${sel.county.state_postal}`;

/** "80 acres (32.4 ha)", or null when the backend gave no area. */
export const areaText = (sel: FieldSelection) => (sel.area_ha != null ? formatAreaBoth(sel.area_ha) : null);

export const placeLine = (sel: FieldSelection) =>
  isBuffered(sel)
    ? `A circle around your point in ${countyLine(sel)}.`
    : `Estimated field area in ${countyLine(sel)}.`;

export const coordsText = (sel: FieldSelection) => formatLatLon(sel.anchor);

const metersAndFeet = (m: number) => `${Math.round(m)} m (${Math.round(metersToFeet(m))} ft)`;

/** The honesty note shown with every field (design copy, three cases). */
export function boundaryNote(sel: FieldSelection): string {
  if (isBuffered(sel)) {
    const radius = sel.buffer_m != null ? `a circle of ${metersAndFeet(sel.buffer_m)}` : "a small circle";
    return `No field outline here, so we use ${radius} around your point. Values are for that circle.`;
  }
  if (sel.resolved_by === "snapped_point" && sel.snap_distance_m) {
    return `This is an estimated field area, snapped from your point to the nearest outline, ${metersAndFeet(sel.snap_distance_m)} away. It is not a legal or ownership boundary.`;
  }
  return "This is an estimated field area from USDA Crop Sequence Boundaries. It can be split or merged compared with the real field, and it is not a legal or ownership boundary.";
}

/** "2025 Corn", newest first, as the backend sends them. */
export const cropHistoryLabels = (sel: FieldSelection) => (sel.crop_history ?? []).map((c) => `${c.year} ${c.crop}`);

/** "Latest mapped crop: Corn (2025)", or null. */
export function latestCropText(sel: FieldSelection): string | null {
  const latest = sel.crop_history?.[0];
  if (latest) return `Latest mapped crop: ${latest.crop} (${latest.year})`;
  return sel.crop_class ? `Latest mapped crop: ${sel.crop_class}` : null;
}

/** What to send back to the API for this field: its id when it has one, otherwise its anchor point. */
export const selectionRef = (sel: FieldSelection): SelectionRef =>
  sel.field_id ? { field_id: sel.field_id } : { point: sel.anchor };

/** Query string that reopens this field on any page (`?field_id=..&lat=..&lon=..`). */
export const selectionSearch = (sel: FieldSelection) => buildFieldSearch({ fieldId: sel.field_id, point: sel.anchor });

/** Rough side length of the field in metres, used for "coarser than this field" warnings. */
export const fieldSizeM = (areaHa: number | null) => (areaHa && areaHa > 0 ? Math.sqrt(areaHa * 10_000) : null);

/** Stable key for a selection (for saving and comparing): field id, else rounded point. */
export const selectionKey = (sel: { field_id: string | null; anchor: LatLon }) =>
  sel.field_id ?? `pt:${sel.anchor.lat.toFixed(5)},${sel.anchor.lon.toFixed(5)}`;
