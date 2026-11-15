import type { ComparisonCell, ComparisonPlan, ComparisonRow, FieldComparison } from "@/entities/comparison";
import { toDisplay, type DisplayValue } from "@/shared/lib";

const MI_PER_KM = 0.621371;

const usdFmt = (digits: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits });
const USD0 = usdFmt(0);
const USD2 = usdFmt(2);

/** "$1,234" or "−$45" (true minus; callers add a "loss" word so the sign is not the only cue). */
export function usd(value: number, digits: 0 | 2 = 0): string {
  const text = (digits === 2 ? USD2 : USD0).format(Math.abs(value));
  return value < 0 && Math.round(Math.abs(value) * 10 ** digits) > 0 ? `−${text}` : text;
}

/**
 * One comparison value as text, in US units. Money units come from the comparison contract
 * (`USD/acre/year`, `USD/year`, `USD/acre/point`); everything else goes through the shared converter.
 */
export function compareValue(value: number | string, unit: string): DisplayValue {
  if (typeof value === "string") return toDisplay(value, unit);
  switch (unit) {
    case "USD/acre/year":
      return { value: usd(value), unit: "per acre a year" };
    case "USD/year":
      return { value: usd(value), unit: "a year" };
    case "USD/acre/point":
      return { value: usd(value, 2), unit: "per acre per point" };
    case "years":
      return { value: String(value), unit: value === 1 ? "year" : "years" };
    case "km":
      return { value: (value * MI_PER_KM).toFixed(1), unit: "mi" };
    case "index":
      return { value: String(Math.round(value)), unit: "of 100" };
    default:
      return toDisplay(value, unit);
  }
}

/** A cell that carries a value the server could read. */
export const hasValue = (c: ComparisonCell | undefined): c is ComparisonCell & { value: number | string } =>
  !!c && c.quality !== "unavailable" && c.value !== null;

export const GROUPS: { key: ComparisonRow["group"]; title: string; lead: string }[] = [
  { key: "money", title: "Money", lead: "Illustrative budget for the crop plan, at each field's rent." },
  { key: "land", title: "Land", lead: "Size, slope and what the land is used for." },
  { key: "soil", title: "Soil", lead: "USDA soil survey, averaged over the field." },
  { key: "history", title: "Crop history", lead: "What grew here in recent years." },
  { key: "climate", title: "Climate", lead: "Long-term regional averages, the same scale for nearby fields." },
];

/** Rows of one group in server order. Unknown groups are never dropped: they land in the last section. */
export function rowsByGroup(rows: readonly ComparisonRow[]): { key: string; title: string; lead: string; rows: ComparisonRow[] }[] {
  const known = new Set(GROUPS.map((g) => g.key));
  const sections = GROUPS.map((g) => ({ ...g, rows: rows.filter((r) => r.group === g.key) }));
  const other = rows.filter((r) => !known.has(r.group));
  const all: { key: string; title: string; lead: string; rows: ComparisonRow[] }[] = sections;
  if (other.length > 0) all.push({ key: "other", title: "Other", lead: "", rows: other });
  return all.filter((s) => s.rows.length > 0);
}

/** Cells of a row in column order (matched by field id, not by position). */
export function cellsInOrder(row: ComparisonRow, fieldIds: readonly string[]): (ComparisonCell | undefined)[] {
  return fieldIds.map((id) => row.cells.find((c) => c.saved_field_id === id));
}

/**
 * Bar lengths (0 to 100) for a "higher is better" numeric row, cells in column order. Null when bars would
 * mislead: negatives, text, a single value, or rows where a shorter value wins.
 */
export function barPercents(row: ComparisonRow, cells: readonly (ComparisonCell | undefined)[]): (number | null)[] | null {
  if (row.better !== "higher" || row.unit === "years") return null;
  const values = cells.map((c) => (hasValue(c) && typeof c.value === "number" ? c.value : null));
  const numbers = values.filter((v): v is number => v !== null);
  if (numbers.length < 2 || numbers.some((v) => v < 0)) return null;
  const max = Math.max(...numbers);
  if (max <= 0) return null;
  return values.map((v) => (v === null ? null : (v / max) * 100));
}

/**
 * The one note every available cell shares (shown once under the row label), or null when they differ.
 * Reasons for missing values are never folded: they stay in their own cell.
 */
export function sharedCellNote(row: ComparisonRow): string | null {
  const available = row.cells.filter(hasValue);
  if (available.length < 2) return null;
  const notes = new Set(available.map((c) => c.note ?? ""));
  const [only] = [...notes];
  return notes.size === 1 && only ? only : null;
}

/** The quality every available cell shares ("measured"), or null when they differ. */
export function sharedQuality(row: ComparisonRow): ComparisonCell["quality"] | null {
  const qualities = new Set(row.cells.filter(hasValue).map((c) => c.quality));
  return qualities.size === 1 ? [...qualities][0]! : null;
}

/** Groups whose rows never fold away, even when every field has the same value. */
export const NEVER_FOLD = new Set<string>(["money"]);

const CROP_NAME = { corn: "corn", soybean: "soybeans", winter_wheat: "winter wheat" } as const;

/** "Corn, then soybeans, over 2 years". */
export function planText(plan: ComparisonPlan): string {
  const crops = (plan.rotation ?? ["corn", "soybean"]).map((c) => CROP_NAME[c]);
  const years = plan.horizon_years ?? 2;
  const list = crops.length === 1 ? `${crops[0]} every year` : crops.join(", then ");
  return `${list.charAt(0).toUpperCase()}${list.slice(1)}, over ${years} ${years === 1 ? "year" : "years"}`;
}

/** The headline cell of a row for one field, by row key. */
export function cellOf(data: FieldComparison, key: string, fieldId: string): ComparisonCell | undefined {
  return data.rows.find((r) => r.key === key)?.cells.find((c) => c.saved_field_id === fieldId);
}
