"""Monthly climate normals + vulnerability timeline for the mock engine.

Normals are rough central Corn Belt values shifted per state. Scenario sliders act the way the
real pipeline will: precip multiplies rainfall, temperature shifts Tmax/Tmin and scales ET0
(~3% per degree, close to the Hargreaves sensitivity in summer).
"""
import math
from dataclasses import dataclass

import numpy as np

from . import crops as crop_db

DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
P_NORM = [28, 30, 55, 90, 120, 120, 105, 100, 80, 70, 55, 35]  # mm / month (~890 / yr)
ET0_NORM = [10, 15, 35, 70, 110, 140, 155, 135, 95, 55, 25, 12]  # mm / month
TMAX = [1, 4, 11, 18, 22.5, 27, 29.5, 28.5, 24, 18, 10, 3]  # degC monthly mean of daily max
TMIN = [-10, -8, -2, 4, 10, 15, 18, 17, 12, 5, -1, -7]
EXTREME_BASE = [0.03, 0.03, 0.07, 0.12, 0.16, 0.18, 0.15, 0.14, 0.11, 0.09, 0.06, 0.03]
SD_TMAX, SD_TMIN = 4.0, 4.5

# per state: (precip factor, et0 factor, temperature offset degC)
STATE_CLIMATE = {
    "IA": (1.00, 1.00, 0.0),
    "IL": (1.09, 0.98, 1.0),
    "NE": (0.73, 1.12, 0.5),
    "KS": (0.81, 1.15, 2.5),
}

TEMP_ET0_PER_C = 0.03
PRECIP_EFFICIENCY = 0.9  # share of monthly rain that is usable in the monthly balance
HEAT_THRESHOLD_C = 32.0


@dataclass(frozen=True)
class Context:
    """everything the engine needs to know about the field and the what-if settings"""
    state: str
    temp_delta: float
    precip_pct: float
    irrigated: bool | None
    has_livestock: bool | None
    om_pct: float
    awc: float
    slope_pct: float
    drainage: str
    language: str

    @property
    def climate(self) -> tuple[float, float, float]:
        return STATE_CLIMATE[self.state]

    def precip_mm(self, month: int) -> float:
        return P_NORM[month] * self.climate[0] * (1 + self.precip_pct / 100)

    def et0_mm(self, month: int) -> float:
        return ET0_NORM[month] * self.climate[1] * (1 + TEMP_ET0_PER_C * self.temp_delta)

    def tmax(self, month: int) -> float:
        return TMAX[month] + self.climate[2] + self.temp_delta

    def tmin(self, month: int) -> float:
        return TMIN[month] + self.climate[2] + self.temp_delta


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(min(hi, max(lo, x)))


def _normal_sf(x: float, mu: float, sd: float) -> float:
    """P(value > x) for a normal distribution"""
    return 0.5 * math.erfc((x - mu) / (sd * math.sqrt(2)))


# a rotation is a list of years; each year is (main crop slug, tuple of cover slugs)
Rotation = list[tuple[str, tuple[str, ...]]]


def year_cover(main: str, covers: tuple[str, ...]) -> np.ndarray:
    """monthly ground cover (0-1) for one rotation year: main crop (with residue floor) + covers"""
    m = crop_db.CATALOG[main]
    cover = np.maximum(np.array(m.curve), m.residue)
    for c in covers:
        cover = 1 - (1 - cover) * (1 - np.array(crop_db.CATALOG[c].curve))
    return cover


def bare_fraction(cover: np.ndarray) -> np.ndarray:
    """share of the month the soil counts as bare (about NDVI < 0.2); half cover is already 'green'"""
    return np.clip(1 - 2 * cover, 0, 1)


def monthly_cover_and_bare(rotation: Rotation) -> tuple[np.ndarray, np.ndarray]:
    covers = np.array([year_cover(m, c) for m, c in rotation])
    return covers.mean(axis=0), bare_fraction(covers).mean(axis=0)


def bare_days(rotation: Rotation) -> int:
    _, bare = monthly_cover_and_bare(rotation)
    return int(round(float((bare * np.array(DAYS)).sum())))


def heat_days(ctx: Context) -> float:
    return sum(_normal_sf(HEAT_THRESHOLD_C, ctx.tmax(m), SD_TMAX) * DAYS[m] for m in range(12))


def moisture_deficit(ctx: Context, cover: float, month: int) -> float:
    """monthly deficit 0-1 from crop demand (FAO-56: Kc x ET0) vs usable rain, buffered by soil awc"""
    kc = min(1.15, 0.3 + 0.8 * cover)
    etc = kc * ctx.et0_mm(month)
    if etc < 1e-6:
        return 0.0
    deficit = _clip((etc - PRECIP_EFFICIENCY * ctx.precip_mm(month)) / etc)
    deficit *= _clip(1.2 - 2.0 * ctx.awc, 0.4, 1.0)  # more stored water -> smaller deficit
    if ctx.irrigated:
        deficit *= 0.3
    return deficit


def build_timeline(rotation: Rotation, ctx: Context) -> list[dict]:
    """12-month vulnerability series for a rotation under the given context"""
    cover, bare = monthly_cover_and_bare(rotation)
    poorly_drained = "poor" in ctx.drainage.lower()
    out = []
    for m in range(12):
        deficit = moisture_deficit(ctx, float(cover[m]), m)
        p_heat = _normal_sf(HEAT_THRESHOLD_C, ctx.tmax(m), SD_TMAX)
        heat = _clip(p_heat * 2.5)
        frost = _clip(1 - _normal_sf(0.0, ctx.tmin(m), SD_TMIN))
        extreme = EXTREME_BASE[m] * (1 + 0.05 * ctx.temp_delta) * (1 + 0.012 * ctx.precip_pct)
        extreme = _clip(extreme * (0.5 + 0.5 * float(bare[m])))
        flags = []
        if bare[m] > 0.7:
            flags.append("bare")
        if deficit > 0.35:
            flags.append("drought")
        if heat > 0.3:
            flags.append("heat")
        if frost > 0.5:
            flags.append("frost")
        if extreme > 0.1:
            flags.append("extreme_rain")
        if poorly_drained and extreme > 0.08:
            flags.append("waterlogging")
        out.append({
            "month": m + 1,
            "bare_soil": round(float(bare[m]), 2),
            "moisture_deficit": round(deficit, 2),
            "heat_stress": round(heat, 2),
            "frost_risk": round(frost, 2),
            "extreme_precip": round(extreme, 2),
            "flags": flags,
        })
    return out
