import type { Coverage } from "@/shared/api";
import type { BBox } from "@/shared/lib";
import type { MapStyleInput } from "@/shared/ui/map";

/** Contiguous US, used until coverage loads (and as the "whole country" view). */
export const CONUS_BBOX: BBox = [-124.8, 24.4, -66.9, 49.4];

/** Map style input from coverage. Field outlines come only from the PMTiles file it names. */
export function mapConfigFrom(coverage: Coverage | undefined): MapStyleInput {
  return {
    fieldTilesUrl: coverage?.field_tiles.url_template ?? null,
    fieldMinZoom: coverage?.field_tiles.min_zoom ?? 12,
    fieldMaxZoom: coverage?.field_tiles.max_zoom ?? 14,
    supportedStates: coverage?.supported_states ?? [],
  };
}

/** "Iowa, Illinois and Nebraska" from coverage regions. */
export function supportedStatesText(coverage: Coverage | undefined): string {
  const names = coverage?.field_tiles.regions.map((r) => r.name) ?? ["Iowa", "Illinois", "Nebraska"];
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
