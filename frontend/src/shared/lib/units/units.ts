/**
 * The API speaks SI (see contract conventions). Everything a farmer reads is converted here,
 * in one place: degC -> °F, mm -> in, m -> ft, ha -> acres. m3/m3 stays m³/m³ (design spec).
 */

export type DisplayValue = { value: string; unit: string };

const ACRES_PER_HA = 2.4710538147;
const FT_PER_M = 3.280839895;
const IN_PER_MM = 1 / 25.4;

export const celsiusToFahrenheit = (c: number) => (c * 9) / 5 + 32;
export const mmToInches = (mm: number) => mm * IN_PER_MM;
export const metersToFeet = (m: number) => m * FT_PER_M;
export const hectaresToAcres = (ha: number) => ha * ACRES_PER_HA;

const fmt = (n: number, decimals: number) =>
  n.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

/** Round acres the way a farmer would say it: "About 78 acres". */
export function formatAcres(ha: number): string {
  const acres = hectaresToAcres(ha);
  if (acres < 10) return fmt(acres, 1);
  return fmt(Math.round(acres), 0);
}

/**
 * Convert one API value + machine unit into display text.
 * Unknown units are shown as-is with their unit, never dropped.
 */
export function toDisplay(value: number | string, unit: string): DisplayValue {
  if (typeof value === "string") return { value, unit: unit === "class" || unit === "none" ? "" : unit };

  switch (unit) {
    case "degC":
      return { value: fmt(celsiusToFahrenheit(value), 0), unit: "°F" };
    case "mm":
      return { value: fmt(mmToInches(value), 1), unit: "in" };
    case "m":
      return { value: fmt(metersToFeet(value), 0), unit: "ft" };
    case "ha":
      return { value: formatAcres(value), unit: "acres" };
    case "m3/m3":
      // Volumetric water content, shown as the satellite products publish it.
      return { value: fmt(value, 2), unit: "m³/m³" };
    case "fraction":
      // 0 to 1 (NASA POWER modeled soil wetness).
      return { value: fmt(value, 2), unit: "" };
    case "%":
      return { value: fmt(value, Math.abs(value) < 10 ? 1 : 0), unit: "%" };
    case "g/kg":
      return { value: fmt(value, 1), unit: "g/kg" };
    case "pH":
      return { value: fmt(value, 1), unit: "pH" };
    case "sd":
      // Standard deviations from normal (soil moisture anomaly). Signed, with a true minus.
      return { value: `${value > 0 ? "+" : value < 0 ? "−" : ""}${fmt(Math.abs(value), 1)}`, unit: "std dev" };
    case "none":
    case "class":
      return { value: fmt(value, value % 1 === 0 ? 0 : 1), unit: "" };
    default:
      return { value: fmt(value, value % 1 === 0 ? 0 : 2), unit };
  }
}

/** Numeric conversion for charts: SI value -> US display number and unit label. */
export function toDisplayNumber(value: number, unit: string): { value: number; unit: string } {
  switch (unit) {
    case "degC":
      return { value: celsiusToFahrenheit(value), unit: "°F" };
    case "mm":
      return { value: mmToInches(value), unit: "in" };
    case "m":
      return { value: metersToFeet(value), unit: "ft" };
    case "m3/m3":
      return { value, unit: "m³/m³" };
    case "fraction":
    case "none":
    case "class":
      return { value, unit: "" };
    default:
      return { value, unit };
  }
}

/** "80 acres (32.4 ha)": the design's area line. */
export function formatAreaBoth(ha: number): string {
  return `${formatAcres(ha)} acres (${fmt(ha, 1)} ha)`;
}

/** Metres to a plain distance a US reader knows: "about 6 mi" or "about 30 ft". */
export function formatDistance(m: number): string {
  const miles = m / 1609.344;
  if (miles >= 0.5) return `${fmt(miles, miles < 10 ? 1 : 0)} mi`;
  return `${fmt(metersToFeet(m), 0)} ft`;
}
