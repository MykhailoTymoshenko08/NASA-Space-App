/**
 * The four cards the Field design shows first, mapped to contract metric keys.
 * Titles come from the design; values, units and sources always come from the backend.
 * Any other metric the backend sends is rendered generically below them.
 */
export type FeaturedMetric = { key: string; title: string; accent: string };

export const FEATURED_METRICS: readonly FeaturedMetric[] = [
  { key: "relative_humidity_2m", title: "Humidity", accent: "var(--color-data-humidity)" },
  { key: "soil_moisture_surface", title: "Soil moisture", accent: "var(--color-data-soil)" },
  { key: "air_temp_mean_2m", title: "Temperature", accent: "var(--color-data-temp)" },
  { key: "soil_nitrogen_total", title: "Nitrogen index", accent: "var(--color-data-nitrogen)" },
];
