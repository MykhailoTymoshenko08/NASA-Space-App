/**
 * The API speaks SI (see contract conventions). Everything a farmer reads is converted here,
 * in one place: degC -> °F, mm -> in, m -> ft, ha -> acres, m3/m3 -> % by volume.
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
    case "mm": {
      const inches = mmToInches(value);
      return { value: fmt(inches, inches < 10 ? 1 : 0), unit: "in" };
    }
    case "m":
      return { value: fmt(metersToFeet(value), 0), unit: "ft" };
    case "ha":
      return { value: formatAcres(value), unit: "acres" };
    case "m3/m3":
      // Volumetric water content as a percentage of soil volume.
      return { value: fmt(value * 100, 0), unit: "% by volume" };
    case "%":
      return { value: fmt(value, 0), unit: "%" };
    case "g/kg":
      return { value: fmt(value, 1), unit: "g/kg" };
    case "pH":
      return { value: fmt(value, 1), unit: "pH" };
    case "none":
    case "class":
      return { value: fmt(value, value % 1 === 0 ? 0 : 1), unit: "" };
    default:
      return { value: fmt(value, value % 1 === 0 ? 0 : 2), unit };
  }
}

/** Metres to a plain distance a US reader knows: "about 6 mi" or "about 30 ft". */
export function formatDistance(m: number): string {
  const miles = m / 1609.344;
  if (miles >= 0.5) return `${fmt(miles, miles < 10 ? 1 : 0)} mi`;
  return `${fmt(metersToFeet(m), 0)} ft`;
}
