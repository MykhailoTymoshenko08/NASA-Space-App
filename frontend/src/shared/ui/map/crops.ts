import type { ExpressionSpecification } from "maplibre-gl";

/**
 * Crop groups for coloring field polygons by their latest `crop_class` (USDA CDL class names,
 * see backend/scripts/cdl_codes.json). Seven groups, not one color per crop: a map with dozens of
 * hues cannot be read. The colors differ in lightness as well as hue, so groups stay apart for
 * color-blind users; from zoom 14 every field also gets a text label with its crop.
 * Colors live in tokens.css (`--color-map-crop-*`).
 */
export type CropGroup = {
  id: string;
  label: string;
  /** CSS custom property with the fill color. */
  token: string;
  /** Used when the token cannot be read (tests, SSR). Must match tokens.css. */
  fallback: string;
  /** CDL class names in this group. The "other" group takes everything not listed elsewhere. */
  names: readonly string[];
};

export const CROP_GROUPS: readonly CropGroup[] = [
  { id: "corn", label: "Corn", token: "--color-map-crop-corn", fallback: "#f2cc5b", names: ["Corn", "Sweet Corn", "Pop or Orn Corn"] },
  { id: "soy", label: "Soybeans", token: "--color-map-crop-soy", fallback: "#5f9e7f", names: ["Soybeans"] },
  {
    id: "grain",
    label: "Wheat and small grains",
    token: "--color-map-crop-grain",
    fallback: "#c9955f",
    names: [
      "Winter Wheat",
      "Spring Wheat",
      "Durum Wheat",
      "Barley",
      "Oats",
      "Rye",
      "Triticale",
      "Millet",
      "Speltz",
      "Buckwheat",
      "Other Small Grains",
    ],
  },
  {
    id: "hay",
    label: "Hay and pasture",
    token: "--color-map-crop-hay",
    fallback: "#9fbf7a",
    names: [
      "Alfalfa",
      "Other Hay/Non Alfalfa",
      "Grassland/Pasture",
      "Pasture/Grass",
      "Clover/Wildflowers",
      "Sod/Grass Seed",
      "Switchgrass",
      "Vetch",
    ],
  },
  { id: "fallow", label: "Fallow or idle", token: "--color-map-crop-fallow", fallback: "#e3d8bd", names: ["Fallow/Idle Cropland"] },
  {
    id: "noncrop",
    label: "Not cropland",
    token: "--color-map-crop-noncrop",
    fallback: "#9eb6bd",
    names: [
      "Forest",
      "Deciduous Forest",
      "Evergreen Forest",
      "Mixed Forest",
      "Shrubland",
      "Barren",
      "Developed",
      "Developed/Open Space",
      "Developed/Low Intensity",
      "Developed/Med Intensity",
      "Developed/High Intensity",
      "Water",
      "Open Water",
      "Wetlands",
      "Woody Wetlands",
      "Herbaceous Wetlands",
      "Nonag/Undefined",
      "Aquaculture",
      "Perennial Ice/Snow",
      "Clouds/No Data",
      "Background",
    ],
  },
  { id: "other", label: "Other or unknown crop", token: "--color-map-crop-other", fallback: "#a99bd0", names: [] },
];

const OTHER = CROP_GROUPS[CROP_GROUPS.length - 1]!;

/** Group of a CDL class name ("Winter Wheat" -> "Wheat and small grains"). Empty or unknown -> other. */
export function cropGroupOf(cropClass: string | null | undefined): CropGroup {
  return CROP_GROUPS.find((g) => cropClass && g.names.includes(cropClass)) ?? OTHER;
}

/** MapLibre `fill-color` expression: `crop_class` -> group color. `colorOf` reads the token. */
export function cropColorExpression(colorOf: (g: CropGroup) => string): ExpressionSpecification {
  const branches = CROP_GROUPS.filter((g) => g.names.length > 0).flatMap((g) => [[...g.names], colorOf(g)]);
  return ["match", ["get", "crop_class"], ...branches, colorOf(OTHER)] as unknown as ExpressionSpecification;
}
