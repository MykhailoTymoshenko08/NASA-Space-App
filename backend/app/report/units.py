"""SI to US display units for the report: the same rules as the frontend `shared/lib/units`."""

from datetime import date

ACRES_PER_HA = 2.4710538147
FT_PER_M = 3.280839895
MM_PER_IN = 25.4


def fmt(n: float, decimals: int) -> str:
    return f"{n:,.{decimals}f}"


def display(value: float | str, unit: str) -> tuple[str, str]:
    """One API value + machine unit as (value, unit) text. Same rules as the frontend `toDisplay`."""
    if isinstance(value, str):
        return value, "" if unit in ("class", "none") else unit
    match unit:
        case "degC":
            return fmt(value * 9 / 5 + 32, 0), "°F"
        case "mm":
            return fmt(value / MM_PER_IN, 1), "in"
        case "m":
            return fmt(value * FT_PER_M, 0), "ft"
        case "ha":
            return acres(value), "acres"
        case "m3/m3":
            return fmt(value, 2), "m³/m³"
        case "fraction":
            return fmt(value, 2), ""
        case "%":
            return fmt(value, 1 if abs(value) < 10 else 0), "%"
        case "g/kg" | "pH":
            return fmt(value, 1), unit
        case "sd":
            sign = "+" if value > 0 else "−" if value < 0 else ""
            return f"{sign}{fmt(abs(value), 1)}", "std dev"
        case "none" | "class":
            return fmt(value, 0 if value % 1 == 0 else 1), ""
        case _:
            return fmt(value, 0 if value % 1 == 0 else 2), unit


def display_number(value: float, unit: str) -> tuple[float, str]:
    """Numeric conversion for charts (frontend `toDisplayNumber`)."""
    match unit:
        case "degC":
            return value * 9 / 5 + 32, "°F"
        case "mm":
            return value / MM_PER_IN, "in"
        case "m":
            return value * FT_PER_M, "ft"
        case "m3/m3":
            return value, "m³/m³"
        case "fraction" | "none" | "class":
            return value, ""
        case _:
            return value, unit


def acres(ha: float) -> str:
    a = ha * ACRES_PER_HA
    return fmt(a, 1) if a < 10 else fmt(round(a), 0)


def short_date(d: date) -> str:
    return f"{d:%b} {d.day}"


def long_date(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def lat_lon(lat: float, lon: float) -> str:
    return f"{abs(lat):.4f}° {'N' if lat >= 0 else 'S'}, {abs(lon):.4f}° {'E' if lon >= 0 else 'W'}"


def resolution(m: float | None) -> str | None:
    if not m:
        return None
    if m >= 1000:
        km = m / 1000
        return f"{fmt(km, 0 if km >= 10 or km % 1 == 0 else 1)} km"
    return f"{fmt(m, 0)} m"


def source_text(dataset: str, provider: str) -> str:
    return f"{dataset}, {provider}"
