/**
 * Crop model validation numbers, copied from ml/models/crop_model/metrics.json
 * (written by ml/scripts/05_train.py, run of 2026-11-14) and ml/docs/pitch_numbers.md.
 * Shares are 0..1. After retraining the model, copy the new numbers here.
 */

export const TRAINED_ON = "2026-11-14";

export const DATASET = {
  fields: 1994,
  fieldSeasons: 12869,
  seasons: "2019–2025",
  historyYears: "2018–2025",
  states: ["Iowa", "Illinois", "Nebraska", "Kansas"],
  features: 53,
  folds: 5,
  precomputedFields: 26224,
} as const;

export type CropKey = "corn" | "soybean" | "winter_wheat" | "sorghum" | "alfalfa";

export const CROPS: readonly { key: CropKey; label: string; rows: number; recall: number }[] = [
  { key: "corn", label: "Corn", rows: 6467, recall: 0.8007 },
  { key: "soybean", label: "Soybean", rows: 4573, recall: 0.8159 },
  { key: "winter_wheat", label: "Winter wheat", rows: 1096, recall: 0.7308 },
  { key: "sorghum", label: "Sorghum", rows: 459, recall: 0.39 },
  { key: "alfalfa", label: "Alfalfa", rows: 274, recall: 0.6569 },
];

/** Rows: the crop that really grew. Columns: the model's first pick. Same order as CROPS. */
export const CONFUSION: readonly (readonly number[])[] = [
  [5178, 1077, 118, 74, 20],
  [771, 3731, 48, 19, 4],
  [177, 46, 801, 63, 9],
  [136, 44, 97, 179, 3],
  [61, 12, 16, 5, 180],
];

export type Method = {
  key: string;
  label: string;
  note: string;
  top1: number;
  top3: number;
  macroF1: number;
  isModel?: boolean;
};

/** Validation on fields the model never saw (5 folds grouped by field). */
export const METHODS: readonly Method[] = [
  {
    key: "model",
    label: "Our model",
    note: "Gradient-boosted trees, calibrated",
    top1: 0.7824,
    top3: 0.9878,
    macroF1: 0.7031,
    isModel: true,
  },
  {
    key: "alternation",
    label: "Corn–soy alternation",
    note: "Corn after soybean, soybean after anything else",
    top1: 0.6674,
    top3: 0.9458,
    macroF1: 0.2887,
  },
  {
    key: "state_most_common",
    label: "State's most common crop",
    note: "Always the crop most planted in the state",
    top1: 0.5025,
    top3: 0.9458,
    macroF1: 0.1338,
  },
  {
    key: "same_as_last_year",
    label: "Same as last year",
    note: "Repeat whatever grew last season",
    top1: 0.2382,
    top3: 0.9618,
    macroF1: 0.3477,
  },
];

/** Top-1 gain over alternation, resampling whole fields (2,000 draws). */
export const GAIN = { value: 0.115, ci95: [0.103, 0.1273] as const };

export const STATES: readonly { code: string; name: string; rows: number; model: number; alternation: number }[] = [
  { code: "IL", name: "Illinois", rows: 3335, model: 0.8327, alternation: 0.8309 },
  { code: "IA", name: "Iowa", rows: 3472, model: 0.8283, alternation: 0.8067 },
  { code: "NE", name: "Nebraska", rows: 3165, model: 0.7798, alternation: 0.6338 },
  { code: "KS", name: "Kansas", rows: 2897, model: 0.6724, alternation: 0.349 },
];

export const CALIBRATION = {
  method: "Temperature scaling",
  temperature: 1.449,
  before: { ece: 0.0657, logLoss: 0.5873, brier: 0.3205 },
  after: { ece: 0.0132, logLoss: 0.5483, brier: 0.3109 },
};

/** Reliability of the top pick: mean stated confidence vs share that was right, per 0.1 bin. */
export type ReliabilityBin = { bin: string; n: number; predicted: number; observed: number };

export const RELIABILITY_BEFORE: readonly ReliabilityBin[] = [
  { bin: "0.2–0.3", n: 2, predicted: 0.287, observed: 0 },
  { bin: "0.3–0.4", n: 70, predicted: 0.361, observed: 0.286 },
  { bin: "0.4–0.5", n: 232, predicted: 0.465, observed: 0.448 },
  { bin: "0.5–0.6", n: 1093, predicted: 0.549, observed: 0.544 },
  { bin: "0.6–0.7", n: 1166, predicted: 0.651, observed: 0.591 },
  { bin: "0.7–0.8", n: 1455, predicted: 0.751, observed: 0.663 },
  { bin: "0.8–0.9", n: 1971, predicted: 0.854, observed: 0.734 },
  { bin: "0.9–1.0", n: 6880, predicted: 0.966, observed: 0.908 },
];

export const RELIABILITY_AFTER: readonly ReliabilityBin[] = [
  { bin: "0.2–0.3", n: 6, predicted: 0.286, observed: 0.167 },
  { bin: "0.3–0.4", n: 133, predicted: 0.358, observed: 0.406 },
  { bin: "0.4–0.5", n: 534, predicted: 0.462, observed: 0.483 },
  { bin: "0.5–0.6", n: 1559, predicted: 0.551, observed: 0.572 },
  { bin: "0.6–0.7", n: 1705, predicted: 0.651, observed: 0.649 },
  { bin: "0.7–0.8", n: 1952, predicted: 0.751, observed: 0.722 },
  { bin: "0.8–0.9", n: 2946, predicted: 0.855, observed: 0.848 },
  { bin: "0.9–1.0", n: 4034, predicted: 0.944, observed: 0.954 },
];

/** Leave one year out: train on six seasons, test on the seventh. */
export const YEARS: readonly { year: number; rows: number; top1: number; macroF1: number }[] = [
  { year: 2019, rows: 1804, top1: 0.7905, macroF1: 0.6716 },
  { year: 2020, rows: 1860, top1: 0.7737, macroF1: 0.7057 },
  { year: 2021, rows: 1864, top1: 0.7994, macroF1: 0.7147 },
  { year: 2022, rows: 1843, top1: 0.8253, macroF1: 0.7707 },
  { year: 2023, rows: 1846, top1: 0.7958, macroF1: 0.7305 },
  { year: 2024, rows: 1823, top1: 0.8168, macroF1: 0.7214 },
  { year: 2025, rows: 1829, top1: 0.83, macroF1: 0.7257 },
];

export const FOLDS: readonly { fold: number; rows: number; top1: number }[] = [
  { fold: 1, rows: 2573, top1: 0.7987 },
  { fold: 2, rows: 2572, top1: 0.7862 },
  { fold: 3, rows: 2573, top1: 0.7851 },
  { fold: 4, rows: 2574, top1: 0.7758 },
  { fold: 5, rows: 2577, top1: 0.7664 },
];

/** Mean |SHAP| share of all attribution, top 15 of 53 features. */
export const DRIVERS: readonly { feature: string; label: string; share: number; crop: string; hint: string }[] = [
  { feature: "prev_crop_1", label: "Crop grown last year", share: 0.1853, crop: "Soybean", hint: "Pushes toward soybean when last year was corn" },
  { feature: "prev_crop_2", label: "Crop grown two years ago", share: 0.047, crop: "Soybean", hint: "Pushes toward soybean when it was soybean" },
  { feature: "lon", label: "Longitude (east–west)", share: 0.0454, crop: "Alfalfa", hint: "Further east, less likely alfalfa" },
  { feature: "norm_srad_grow", label: "Typical season sunshine", share: 0.0377, crop: "Sorghum", hint: "More sun, more likely sorghum" },
  { feature: "norm_heat_days_35", label: "Typical days above 35 °C", share: 0.0367, crop: "Winter wheat", hint: "More hot days, more likely winter wheat" },
  { feature: "norm_tmax_summer", label: "Typical summer high", share: 0.0354, crop: "Sorghum", hint: "Hotter summers, more likely sorghum" },
  { feature: "norm_heat_days_32", label: "Typical days above 32 °C", share: 0.0288, crop: "Winter wheat", hint: "More hot days, more likely winter wheat" },
  { feature: "lat", label: "Latitude (north–south)", share: 0.0283, crop: "Sorghum", hint: "Further north, less likely sorghum" },
  { feature: "om_pct", label: "Soil organic matter", share: 0.0226, crop: "Sorghum", hint: "Richer soil, less likely sorghum" },
  { feature: "norm_et0_grow", label: "Typical season evaporation", share: 0.0223, crop: "Winter wheat", hint: "Thirstier air, more likely winter wheat" },
  { feature: "slope_pct", label: "Field slope", share: 0.0211, crop: "Alfalfa", hint: "Steeper field, less likely alfalfa" },
  { feature: "lag1_srad_grow", label: "Last season's sunshine", share: 0.0205, crop: "Sorghum", hint: "Sunnier last season, more likely sorghum" },
  { feature: "clay_pct", label: "Soil clay", share: 0.0202, crop: "Alfalfa", hint: "More clay, more likely alfalfa" },
  { feature: "awc_cm_cm", label: "Soil water-holding capacity", share: 0.0191, crop: "Winter wheat", hint: "Holds more water, less likely winter wheat" },
  { feature: "kw_factor", label: "Soil erodibility (K factor)", share: 0.0185, crop: "Alfalfa", hint: "More erodible, more likely alfalfa" },
];

/** Literature limits vs where each crop really grew (ml/docs/suitability_literature_vs_real.md). */
export const LITERATURE_CHECK = { crops: 5, measures: 7, insideLimits: "99–100%", insidePlateau: "52–100%" };

export const LIMITS: readonly string[] = [
  "It predicts which crop a field will carry next season, not yield or income.",
  "It was tested on new fields in the same four states. Expect weaker results in a new region.",
  "It sees the typical weather and last season, not the season ahead: a drought year or a disease outbreak is invisible to it.",
  "Sorghum is the weak spot: the model finds 39% of real sorghum fields and often reads them as corn or wheat.",
  "In Iowa and Illinois, where rotations are nearly fixed, it is only as good as the corn–soy rule.",
];
