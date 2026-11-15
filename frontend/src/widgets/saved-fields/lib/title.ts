import { buildFieldSearch } from "@/entities/field";
import type { SavedField } from "@/entities/saved-field";
import { formatLatLon } from "@/shared/lib";

export const isPoint = (f: SavedField) => f.geometry.type === "Point";

export const savedKind = (f: SavedField) =>
  isPoint(f) ? "Circle around a point" : f.field_id ? "Estimated field area" : "Saved outline";

/** Polygon rings for the sketch; none for a point. */
export const savedRings = (f: SavedField) => (f.geometry.type === "Polygon" ? f.geometry.coordinates : []);

/** Query string that opens this field on the Field page. */
export const savedSearch = (f: SavedField) => buildFieldSearch({ fieldId: f.field_id, point: f.centroid });

export const savedCoords = (f: SavedField) => formatLatLon(f.centroid);

/** Newest crop the user or the map recorded, or null. */
export const savedCrop = (f: SavedField) => f.crop_history?.[0]?.crop ?? null;
