import type { FieldSelection } from "@/shared/api";

/** "Polk, IA" for a field; "Point near Polk, IA" for a buffered circle. */
export const savedTitle = (sel: FieldSelection) =>
  `${sel.field_id ? "" : "Point near "}${sel.county.name}, ${sel.county.state_postal}`;

/** Short id for narrow table headers: "…123456". */
export const shortId = (sel: FieldSelection) => (sel.field_id ? `…${sel.field_id.slice(-6)}` : "Circle, no outline");
