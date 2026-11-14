"""Agro calculator at the level of a rotation (a chain of years, with optional winter cover crops).

It turns a chain such as [corn, soybean, corn] (+ cereal rye after some years) into
  bare soil days per year, nitrogen balance, water use (Kc x ET0, FAO-56), erosion (simplified RUSLE),
  pest cycle break (yes / no), and the five 0-100 scores the farmer's priorities weigh.

The crop table is DRAFT: rough Corn Belt values, not calibrated. Cover curves and Kc are monthly (Jan..Dec).
The rotation is treated as a steady state: the spring part of a cover grown after the last year wraps to the first year.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DAYS = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], dtype=float)
FALL, SPRING = slice(9, 12), slice(0, 5)      # months a winter cover occupies: Oct-Dec and Jan-May
T_VALUE = 11.2                                # tolerable soil loss, t/ha/yr (5 t/ac)
SLOPE_LENGTH_M = 50.0                         # no field slope length in the data: one typical value
WATER_EFFICIENCY = 0.6                        # share of yearly rain that is usable
ROOT_ZONE_STORAGE = 500.0                     # mm per unit of awc (cm/cm): half of a 1 m root zone
IRRIGATION_MM = 250.0

Vec = tuple


@dataclass(frozen=True)
class AgroCrop:
    kc: Vec                 # monthly crop coefficient (FAO-56), crop + soil evaporation while it grows
    cover: Vec              # monthly ground cover 0-1
    residue: float          # winter ground cover left by the crop
    c_factor: float         # RUSLE cover-management factor (mixed tillage)
    n_fix: float            # kg N/ha/yr fixed biologically
    n_net: float            # kg N/ha/yr net balance (negative = removal)
    income: float           # 0-100 relative margin
    heat_sens: float        # 0-1
    drought_sens: float     # 0-1
    legume: bool = False
    perennial: bool = False
    autumn_harvest: bool = False   # harvested early enough to sow a winter cover afterwards


CROPS: dict[str, AgroCrop] = {
    "corn": AgroCrop((0, 0, 0, .2, .35, .7, 1.15, 1.2, .9, .4, 0, 0), (0, 0, 0, .05, .15, .4, .9, 1, .9, .4, 0, 0),
                     .12, .20, 0, -120, 82, 1.0, 1.0, autumn_harvest=True),
    "soybean": AgroCrop((0, 0, 0, 0, .2, .4, .9, 1.15, .7, .3, 0, 0), (0, 0, 0, 0, .05, .2, .7, 1, .9, .2, 0, 0),
                        .06, .25, 60, 30, 74, .6, .7, legume=True, autumn_harvest=True),
    "sorghum": AgroCrop((0, 0, 0, 0, .2, .4, .9, 1.0, .8, .3, 0, 0), (0, 0, 0, 0, .05, .2, .6, .95, .95, .5, 0, 0),
                        .12, .20, 0, -90, 64, .1, .3, autumn_harvest=True),
    "winter_wheat": AgroCrop((.3, .3, .5, .9, 1.15, .9, .25, 0, 0, .3, .4, .3), (.25, .25, .35, .6, .9, .95, .3, .05, .05, .2, .4, .3),
                             .12, .12, 0, -60, 60, .2, .5),
    "oats": AgroCrop((0, 0, 0, .3, .7, 1.1, .8, .2, 0, 0, 0, 0), (0, 0, 0, 0, .3, .8, .9, .2, 0, 0, 0, 0),
                     .08, .12, 0, -50, 48, .4, .6),
    "barley": AgroCrop((0, 0, 0, .3, .75, 1.1, .7, .15, 0, 0, 0, 0), (0, 0, 0, 0, .35, .85, .85, .15, 0, 0, 0, 0),
                       .08, .12, 0, -50, 50, .5, .6),
    "alfalfa": AgroCrop((0, 0, .3, .7, 1.0, 1.1, 1.1, 1.0, .9, .6, .2, 0), (.2, .2, .3, .6, .9, 1, 1, 1, .95, .7, .4, .25),
                        0.0, .02, 150, 120, 58, .4, .5, legume=True, perennial=True),
    # fallow: bare soil all year, nothing harvested (dryland wheat-fallow). never offered as a choice
    "fallow": AgroCrop((.1,) * 12, (0,) * 12, .08, .45, 0, -20, 0, 0.0, 0.0),
    # anything else the history says ("other"): a generic profile, never offered as a choice
    "other": AgroCrop((.1,) * 12, (0,) * 12, .05, .45, 0, -20, 35, .3, .5),
}
COVER = {   # winter cover crop sown after harvest
    # kc = EXTRA water use of the cover over bare soil (soil evaporation happens anyway); terminated in early May.
    # the dead mulch keeps covering the ground afterwards (cover in May-June). ~65 mm/yr extra at 50-60 cm of rye growth
    "cereal_rye": dict(kc=(.05, .05, .15, .45, .15, 0, 0, 0, 0, .1, .15, .1), cover=(.2, .2, .25, .5, .75, .2, 0, 0, 0, .1, .25, .25),
                       c_mult=.5, n_net=10.0, cost=3.0),
}
SCORE_KEYS = ("water", "soil_health", "nitrogen", "erosion", "income")


def profile(token: str) -> AgroCrop:
    """profile of one rotation year. a double crop "a+b" is the first crop up to June and the second one after it
    (the second crop yields less when sown late: 70% of its income)."""
    if "+" not in token:
        return CROPS.get(token, CROPS["other"])
    first, second = (CROPS.get(c, CROPS["other"]) for c in token.split("+"))
    return AgroCrop(
        kc=first.kc[:6] + second.kc[6:], cover=first.cover[:6] + second.cover[6:], residue=max(first.residue, second.residue),
        c_factor=(first.c_factor + second.c_factor) / 2 * 0.85, n_fix=first.n_fix + second.n_fix, n_net=first.n_net + second.n_net,
        income=first.income + 0.7 * second.income, heat_sens=max(first.heat_sens, second.heat_sens),
        drought_sens=max(first.drought_sens, second.drought_sens), legume=first.legume or second.legume,
        autumn_harvest=second.autumn_harvest)


@dataclass
class AgroResult:
    scores: dict[str, float]
    water_use_mm: float
    n_fixed: float
    n_net: float
    bare_days: float
    erosion_t_ha: float
    pest_break: bool
    pest_pairs: list[tuple[str, str]]
    water_ratio: float
    r_factor: float


# --------------------------------------------------------------------------- RUSLE pieces

def rainfall_erosivity(p_annual_mm: float) -> float:
    """R, MJ mm/(ha h yr), from annual rain (Renard & Freimund 1994)."""
    return 0.0483 * p_annual_mm ** 1.61 if p_annual_mm <= 850 else 587.8 - 1.219 * p_annual_mm + 0.004105 * p_annual_mm ** 2


def slope_factor(slope_pct: float, length_m: float = SLOPE_LENGTH_M) -> float:
    s = max(float(slope_pct), 0.5)
    theta = np.arctan(s / 100.0)
    sin = np.sin(theta)
    beta = (sin / 0.0896) / (3.0 * sin ** 0.8 + 0.56)
    m = beta / (1.0 + beta)
    ls_l = (length_m / 22.13) ** m
    ls_s = 10.8 * sin + 0.03 if s < 9 else 16.8 * sin - 0.50
    return float(ls_l * ls_s)


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return float(min(hi, max(lo, x)))


# --------------------------------------------------------------------------- the calculator

def evaluate(steps: list[str], covers: list[bool], prev_actual: str, *, et0_monthly, precip_annual: float, kw_factor: float,
             slope_pct: float, om_pct: float, awc: float, irrigated: bool | None = None, has_livestock: bool | None = None,
             temp_delta_c: float = 0.0, precip_change_pct: float = 0.0, cover_crop: str = "cereal_rye") -> AgroResult:
    """steps: crop per year; covers[j]: a winter cover is sown after year j. prev_actual: the real previous crop."""
    n = len(steps)
    et0 = np.asarray(et0_monthly, dtype=float)
    cov = COVER[cover_crop]
    water, bare, n_net, n_fix, c_vals, income = [], [], [], [], [], []
    for j, crop in enumerate(steps):
        c = profile(crop)
        spring_cover = covers[(j - 1) % n]   # cover sown after the previous year (wraps for the first year)
        fall_cover = covers[j]
        kc = np.array(c.kc, dtype=float)
        ground = np.maximum(np.array(c.cover, dtype=float), c.residue)
        if spring_cover:
            kc[SPRING] = kc[SPRING] + np.array(cov["kc"])[SPRING]
            ground[SPRING] = 1 - (1 - ground[SPRING]) * (1 - np.array(cov["cover"])[SPRING])
        if fall_cover:
            kc[FALL] = kc[FALL] + np.array(cov["kc"])[FALL]
            ground[FALL] = 1 - (1 - ground[FALL]) * (1 - np.array(cov["cover"])[FALL])
        water.append(float((np.minimum(kc, 1.3) * et0).sum()))
        bare.append(float((np.clip(1 - 2 * ground, 0, 1) * DAYS).sum()))
        n_net.append(c.n_net + (cov["n_net"] if fall_cover else 0.0))
        n_fix.append(c.n_fix)
        c_vals.append(c.c_factor * (cov["c_mult"] if fall_cover else 1.0))

        inc = c.income - (cov["cost"] if fall_cover else 0.0)
        inc -= c.heat_sens * 4.0 * max(0.0, temp_delta_c)           # warming hurts heat-sensitive crops
        inc -= c.drought_sens * 0.25 * max(0.0, -precip_change_pct)  # so does less rain
        if crop == "alfalfa":   # forage needs a market or livestock; unknown is treated with caution
            inc += 15 if has_livestock is True else (-10 if has_livestock is False else -5)
        income.append(inc)

    water_use = float(np.mean(water))
    supply = WATER_EFFICIENCY * precip_annual + awc * ROOT_ZONE_STORAGE + (IRRIGATION_MM if irrigated else 0.0)
    ratio = supply / max(water_use, 1.0)

    r = rainfall_erosivity(precip_annual)
    a_loss = r * (kw_factor * 0.1317) * slope_factor(slope_pct) * float(np.mean(c_vals))

    mains = [c for s in steps for c in s.split("+") if c not in ("other", "fallow")]
    distinct = min(len(set(mains)), 3)
    legume_frac = sum(profile(s).legume for s in steps) / n
    perennial_frac = sum(profile(s).perennial for s in steps) / n
    cover_frac = sum(covers) / n
    soil = 12 + 8 * distinct + 8 * legume_frac + 28 * cover_frac + 35 * perennial_frac + min(15.0, 3 * om_pct)

    pairs = [(prev_actual, steps[0]), *zip(steps, steps[1:])]
    repeats = [(x, y) for x, y in pairs if x == y and x not in ("other", "fallow") and "+" not in x and not profile(x).perennial]

    return AgroResult(
        scores={
            "water": _clip(100 * (ratio - 0.7) / 0.9),
            "soil_health": _clip(soil),
            "nitrogen": _clip(60 + 0.3 * float(np.mean(n_net))),
            "erosion": _clip(100 * (1 - a_loss / (2 * T_VALUE))),
            "income": _clip(float(np.mean(income))),
        },
        water_use_mm=water_use, n_fixed=float(np.mean(n_fix)), n_net=float(np.mean(n_net)),
        bare_days=float(np.mean(bare)), erosion_t_ha=a_loss, pest_break=not repeats, pest_pairs=repeats,
        water_ratio=ratio, r_factor=r,
    )
