import type { FieldSelection } from "@/shared/api";
import { formatAcres, formatDistance } from "@/shared/lib";

export const fieldTitle = (sel: FieldSelection) => (sel.field_id ? `Field ${sel.field_id}` : "Your point");

export const countyLine = (sel: FieldSelection) => `${sel.county.name} County, ${sel.county.state_postal}`;

export const areaLine = (sel: FieldSelection) => (sel.area_ha != null ? `About ${formatAcres(sel.area_ha)} acres` : null);

/**
 * Honesty note shown next to the field sketch. Polygons are estimates, not surveyed boundaries.
 * Wording from the frontend spec.
 */
export function boundaryNote(sel: FieldSelection): string {
  if (sel.resolved_by === "buffered_point") {
    const radius = sel.buffer_m != null ? `${Math.round(sel.buffer_m)} m` : "small";
    return `No mapped field here. We'll analyse a ${radius} circle around your point.`;
  }
  const base = "Estimated field area. Outlines come from mapped crop data, not a survey.";
  if (sel.resolved_by === "snapped_point" && sel.snap_distance_m) {
    return `${base} We moved your point ${formatDistance(sel.snap_distance_m)} to the nearest field.`;
  }
  return base;
}
