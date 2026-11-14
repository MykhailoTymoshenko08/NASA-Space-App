import { CROP_GROUPS } from "../map/crops";
import type { LegendItem } from "./MapOverlay";

/** Field fill by latest crop group, matching the map style (shared/ui/map/crops.ts). */
export const CROP_LEGEND_ITEMS: readonly LegendItem[] = CROP_GROUPS.map((g) => ({
  label: g.label,
  fill: `var(${g.token})`,
  line: "var(--color-map-field-line)",
}));

/** Outline of the signed-in user's saved fields. */
export const SAVED_LEGEND_ITEM: LegendItem = {
  label: "Your saved field (labeled with its name)",
  fill: "transparent",
  line: "var(--color-map-saved)",
};

/** Survey township (PLSS), dashed on the map: the step between a county and its fields. */
export const TOWNSHIP_LEGEND_ITEM: LegendItem = {
  label: "Township (6 by 6 miles)",
  fill: "transparent",
  line: "var(--color-map-region-line)",
};

/** Survey section (PLSS), numbered 1 to 36 inside its township. */
export const SECTION_LEGEND_ITEM: LegendItem = {
  label: "Section (1 square mile, numbered)",
  fill: "transparent",
  line: "var(--color-map-label-muted)",
};
