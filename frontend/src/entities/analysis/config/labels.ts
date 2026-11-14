import type { Priority, Strategy } from "@/shared/api";

/** Farmer-facing names for contract enums (design copy). */
export const PRIORITY_LABEL: Record<Priority, string> = {
  water_conservation: "Save water",
  extra_income: "Extra income",
  soil_health: "Soil health",
  erosion_control: "Less erosion",
  low_input_cost: "Low input cost",
  nitrogen_fixing: "Add nitrogen naturally",
};
export const PRIORITIES = Object.keys(PRIORITY_LABEL) as Priority[];

type Role = Strategy["rotation"][number]["role"];
export const ROLE_LABEL: Record<Role, string> = {
  cash_crop: "Cash crop",
  cover_crop: "Cover crop",
  nitrogen_fixer: "Nitrogen fixer",
  forage: "Forage",
  fallow: "Fallow",
};

type Criterion = NonNullable<Strategy["score_breakdown"]>[number]["criterion"];
export const CRITERION_LABEL: Record<Criterion, string> = {
  water_use: "Water use",
  soil_health: "Soil health",
  erosion: "Erosion",
  nitrogen: "Nitrogen",
  pest_cycle: "Pest cycle",
  income: "Income",
  climate_risk: "Climate risk",
};

export const HORIZONS = [1, 2, 3, 4, 5] as const;
export const DEFAULT_HORIZON = 3;

export const priorityText = (picked: readonly Priority[]) =>
  picked.length ? picked.map((p) => PRIORITY_LABEL[p]).join(", ") : "Balanced";

export const yearsText = (n: number) => `${n} ${n === 1 ? "year" : "years"}`;
