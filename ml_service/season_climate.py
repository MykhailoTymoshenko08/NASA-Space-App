"""Climate normals of a field from the cached NASA POWER daily data, with what-if shifts.

The formulas are the same as in scripts/02_power_climate.py (season features, Hargreaves ET0) and
scripts/03b_winter_tmin.py (winter minimum); a test checks that with no shift the result equals the stored tables.
A scenario shifts temperature (T2M, T2M_MAX, T2M_MIN += temp_delta_c) and rain (x (1 + precip_change_pct / 100)) day by
day and everything is recomputed: the 18 season features, ET0, monthly profiles and the winter minimum.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

FILL_VALUE = -999.0
GROW_MONTHS = range(4, 10)
SUMMER_MONTHS = range(6, 9)
SPRING_MONTHS = range(4, 7)
CLIMATE_COLS = [
    "gdd_grow", "tmean_grow", "tmax_summer", "heat_days_32", "heat_days_35", "precip_grow", "precip_spring",
    "precip_summer", "et0_grow", "water_balance_grow", "max_dry_spell", "extreme_rain_days_spring",
    "extreme_rain_days_year", "last_spring_frost_doy", "first_fall_frost_doy", "frost_free_days",
    "srad_grow", "rh_summer",
]


def _extraterrestrial_radiation(doy: np.ndarray, lat_deg: float) -> np.ndarray:
    lat = math.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    decl = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(lat) * np.tan(decl), -1, 1))
    ra_mj = (24 * 60 / np.pi) * 0.0820 * dr * (ws * np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.sin(ws))
    return 0.408 * ra_mj


def hargreaves_et0(tmax, tmin, tmean, doy, lat: float):
    """reference evapotranspiration, mm/day (Hargreaves-Samani). needs only temperature, so a warmer climate changes it."""
    ra = _extraterrestrial_radiation(doy, lat)
    return (0.0023 * ra * (tmean + 17.8) * np.sqrt((tmax - tmin).clip(lower=0))).clip(lower=0)


def _gdd(tmax, tmin, base: float = 10.0, cap: float = 30.0):
    return (((tmax.clip(lower=base, upper=cap) + tmin.clip(lower=base, upper=cap)) / 2) - base).clip(lower=0)


def _longest_run(mask: pd.Series) -> int:
    best = cur = 0
    for v in mask.to_numpy():
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


@lru_cache(maxsize=16)
def load_daily(cache_file: str, lat: float) -> pd.DataFrame:
    """POWER json -> daily frame (tmean, tmax, tmin, precip, rh, wind, srad, et0)."""
    p = json.loads(Path(cache_file).read_text())["properties"]["parameter"]
    df = pd.DataFrame({k: pd.Series(v) for k, v in p.items()})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.replace(FILL_VALUE, np.nan).sort_index().rename(columns={
        "T2M": "tmean", "T2M_MAX": "tmax", "T2M_MIN": "tmin", "PRECTOTCORR": "precip",
        "RH2M": "rh", "WS2M": "wind", "ALLSKY_SFC_SW_DWN": "srad"})
    df["et0"] = hargreaves_et0(df["tmax"], df["tmin"], df["tmean"], df.index.day_of_year.to_numpy(), lat)
    return df


def shift(daily: pd.DataFrame, temp_delta_c: float, precip_change_pct: float, lat: float) -> pd.DataFrame:
    """what-if climate: every day warmer/colder by temp_delta_c, rain scaled; ET0 recomputed from the new temperatures."""
    if temp_delta_c == 0 and precip_change_pct == 0:
        return daily
    d = daily.copy()
    for c in ("tmean", "tmax", "tmin"):
        d[c] = d[c] + temp_delta_c
    d["precip"] = d["precip"] * (1 + precip_change_pct / 100.0)
    d["et0"] = hargreaves_et0(d["tmax"], d["tmin"], d["tmean"], d.index.day_of_year.to_numpy(), lat)
    return d


def season_features(daily: pd.DataFrame) -> pd.DataFrame:
    """one row per year, the 18 season features (same as scripts/02_power_climate.py)."""
    rows = []
    for year, d in daily.groupby(daily.index.year):
        m = d.index.month
        grow, summer, spring = d[m.isin(GROW_MONTHS)], d[m.isin(SUMMER_MONTHS)], d[m.isin(SPRING_MONTHS)]
        if len(grow) < 150:
            continue
        first_half = d[(d.index.month < 7) & (d["tmin"] < 0)]
        second_half = d[(d.index.month >= 7) & (d["tmin"] < 0)]
        last_spring = int(first_half.index.day_of_year.max()) if len(first_half) else np.nan
        first_fall = int(second_half.index.day_of_year.min()) if len(second_half) else np.nan
        pg, eg = grow["precip"].sum(), grow["et0"].sum()
        rows.append({
            "year": year, "gdd_grow": _gdd(grow["tmax"], grow["tmin"]).sum(), "tmean_grow": grow["tmean"].mean(),
            "tmax_summer": summer["tmax"].mean(), "heat_days_32": int((summer["tmax"] > 32).sum()),
            "heat_days_35": int((summer["tmax"] > 35).sum()), "precip_grow": pg, "precip_spring": spring["precip"].sum(),
            "precip_summer": summer["precip"].sum(), "et0_grow": eg, "water_balance_grow": pg - eg,
            "max_dry_spell": _longest_run(d[d.index.month.isin(range(5, 9))]["precip"] < 1.0),
            "extreme_rain_days_spring": int((spring["precip"] > 25).sum()), "extreme_rain_days_year": int((d["precip"] > 25).sum()),
            "last_spring_frost_doy": last_spring, "first_fall_frost_doy": first_fall,
            "frost_free_days": (first_fall - last_spring) if not (np.isnan(last_spring) or np.isnan(first_fall)) else np.nan,
            "srad_grow": grow["srad"].mean(), "rh_summer": summer["rh"].mean(),
        })
    return pd.DataFrame(rows)


def winter_tmin(daily: pd.DataFrame) -> float:
    """mean over winters (Dec of year-1 + Jan + Feb) of the lowest daily T2M_MIN, complete winters only."""
    s = daily["tmin"][daily.index.month.isin([12, 1, 2])]
    g = s.groupby(s.index.year + (s.index.month == 12))
    mins = g.min()[g.count() >= 85]
    return float(mins.mean())


def normals(daily: pd.DataFrame) -> dict:
    """the field's climate normal: 18 season features, monthly profiles (mm, degC) and the winter minimum."""
    sf = season_features(daily)
    monthly = daily.groupby([daily.index.year, daily.index.month]).agg(et0=("et0", "sum"), precip=("precip", "sum"),
                                                                       tmean=("tmean", "mean"))
    m = monthly.groupby(level=1).mean()
    return {
        "climate_norm": {c: float(sf[c].mean()) for c in CLIMATE_COLS},
        "et0_monthly": m["et0"].reindex(range(1, 13)).tolist(),
        "precip_monthly": m["precip"].reindex(range(1, 13)).tolist(),
        "tmean_monthly": m["tmean"].reindex(range(1, 13)).tolist(),
        "precip_annual": float(m["precip"].sum()),
        "winter_tmin_c": winter_tmin(daily),
    }
