import type { Metric } from "@/shared/api";
import { mmToInches } from "@/shared/lib";

export type GlossaryTerm = { id: string; term: string; def: string };

/** Glossary at the bottom of Base conditions and Analysis (design copy). */
export const GLOSSARY: readonly GlossaryTerm[] = [
  {
    id: "gl-ndvi",
    term: "NDVI (plant greenness)",
    def: "A score from about 0 to 1 for how much green plant cover a satellite sees. Bare soil is near 0 and thick healthy crops are above 0.6.",
  },
  {
    id: "gl-et",
    term: "ET (evapotranspiration)",
    def: "The water that moves from the field to the air, both from soil drying out and from plants releasing it. It is the main way a field loses water besides runoff.",
  },
  {
    id: "gl-anomaly",
    term: "Soil moisture anomaly",
    def: "The gap between today's soil moisture and what is normal for this date. Negative means drier than normal and positive means wetter.",
  },
  {
    id: "gl-sd",
    term: "Standard deviation (std dev)",
    def: "A yardstick for how unusual a reading is. Within 1 either way is ordinary. Beyond 2 is rare.",
  },
  {
    id: "gl-surface",
    term: "Surface soil moisture",
    def: "Water in the top few centimeters of soil. It changes fast after rain or wind.",
  },
  {
    id: "gl-rootzone",
    term: "Root-zone soil moisture",
    def: "Water down to about 1 meter, where most crop roots drink. It changes more slowly.",
  },
  {
    id: "gl-vol",
    term: "m³/m³ (volumetric moisture)",
    def: "Share of the soil volume that is water. 0.27 means 27 percent of the soil is water.",
  },
  {
    id: "gl-normal",
    term: "Normal (climatology)",
    def: "The long-term average for a place and date, taken from past years.",
  },
  {
    id: "gl-pixel",
    term: "Pixel size",
    def: "The size of one square in the source data. One reading covers the whole square, so large pixels describe the area around a field, not the field itself.",
  },
  {
    id: "gl-quality",
    term: "Measured, Modeled, Estimate",
    def: "Measured values come straight from an instrument or survey. Modeled values come from a computer model fed with measurements. An estimate is our own calculation from other values.",
  },
  {
    id: "gl-som",
    term: "Soil organic matter",
    def: "Decayed plant and animal material in the soil. More of it usually means better water holding and more nutrients.",
  },
  {
    id: "gl-ph",
    term: "Soil pH",
    def: "How acid or alkaline the soil is. Most crops do best between 6 and 7.",
  },
];

export type MetricHint = { what: string; read: string; glossaryId: string };

/** Info hints (NDVI, ET and soil moisture anomaly only). */
export const HINTS: Readonly<Record<string, MetricHint>> = {
  vegetation_index_ndvi: {
    what: "A score for how green and leafy the plants on the field are, taken from satellite images.",
    read: "Near 0 is bare soil. 0.2 to 0.5 is light or young cover. 0.6 to 0.9 is thick, healthy green. Stubble or snow reads low even on a good field.",
    glossaryId: "gl-ndvi",
  },
  et_30d_total: {
    what: "Evapotranspiration (ET) is the water that leaves the field as plants release it and the soil dries out.",
    read: "Compare it with rain. When rain stays below ET for weeks, the soil dries down. Shown in inches over the last 30 days.",
    glossaryId: "gl-et",
  },
  soil_moisture_anomaly: {
    what: "How much wetter or drier the soil is than usual for this time of year, compared with 2015 to 2025.",
    read: "Zero is normal. Below -1 is clearly dry and above +1 is clearly wet. The unit is standard deviation, a way to say how unusual a reading is.",
    glossaryId: "gl-anomaly",
  },
};

/**
 * A plain-language reading of a value, worked out in the UI (not sent by the API).
 * Empty when there is nothing to say or the value is missing.
 */
export function readingFor(m: Metric, all: readonly Metric[]): string {
  const v = m.value;
  if (typeof v !== "number") return "";
  if (m.key === "vegetation_index_ndvi") {
    return v < 0.15
      ? "Bare soil or snow."
      : v < 0.35
        ? "Light cover, such as stubble or a young cover crop."
        : v < 0.6
          ? "Moderate green cover."
          : "Thick, healthy green cover.";
  }
  if (m.key === "soil_moisture_anomaly") {
    return v < -1.5
      ? "Much drier than normal."
      : v < -0.5
        ? "A bit drier than normal."
        : v <= 0.5
          ? "About normal."
          : v <= 1.5
            ? "A bit wetter than normal."
            : "Much wetter than normal.";
  }
  if (m.key === "et_30d_total" && m.unit === "mm") {
    const rain = all.find((x) => x.key === "precip_30d_total");
    if (!rain || typeof rain.value !== "number" || rain.unit !== "mm") return "";
    const r = rain.value;
    const rel = Math.abs(r - v) < 0.1 * v ? "about the same as" : r > v ? "more than" : "less than";
    return `Rain over the same 30 days was ${mmToInches(r).toFixed(1)} in, ${rel} the ${mmToInches(v).toFixed(1)} in the field gave back.`;
  }
  return "";
}
