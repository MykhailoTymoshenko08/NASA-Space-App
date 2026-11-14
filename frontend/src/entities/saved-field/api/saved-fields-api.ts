import { api, unwrap, type FieldSelection, type SavedFieldCreate, type SavedFieldDto } from "@/shared/api";

/** A saved field as the API returns it (GET /me/fields). */
export type SavedField = SavedFieldDto;

/** Saved fields of the signed-in user. Every call sends the bearer token (shared/api client). */
export const savedFieldsApi = {
  list: () => unwrap(api.GET("/me/fields")),
  create: (body: SavedFieldCreate) => unwrap(api.POST("/me/fields", { body })),
  remove: (id: string) =>
    unwrap(api.DELETE("/me/fields/{saved_field_id}", { params: { path: { saved_field_id: id } } })),
};

/** "Polk, IA": default name for a newly saved field. */
export const defaultName = (sel: FieldSelection) =>
  `${sel.field_id ? "" : "Point near "}${sel.county.name}, ${sel.county.state_postal}`;

/**
 * Request body for a selection. A mapped field sends its polygon and id; a buffered circle is not a
 * field, so it is saved as the point the user picked.
 */
export function createBodyFor(sel: FieldSelection): SavedFieldCreate {
  const buffered = sel.resolved_by === "buffered_point";
  return {
    name: defaultName(sel).slice(0, 100),
    field_id: buffered ? null : sel.field_id,
    geometry: buffered ? { type: "Point", coordinates: [sel.anchor.lon, sel.anchor.lat] } : sel.geometry,
    crop_history: sel.crop_history && sel.crop_history.length > 0 ? sel.crop_history.slice(0, 10) : null,
  };
}

const near = (a: number, b: number) => Math.abs(a - b) < 1e-5;

/** Whether a saved field is this selection: same CSB id, or the same picked point. */
export function matchesSelection(saved: SavedField, sel: FieldSelection): boolean {
  if (sel.field_id && saved.field_id) return saved.field_id === sel.field_id;
  if (sel.field_id || saved.field_id) return false;
  const g = saved.geometry;
  return g.type === "Point" && near(g.coordinates[0] ?? NaN, sel.anchor.lon) && near(g.coordinates[1] ?? NaN, sel.anchor.lat);
}
