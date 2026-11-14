"""Builds a FieldContext from the precomputed tables in data/ (what the service will keep for the demo region).

Same recipe as scripts/04_build_dataset.py: previous crops, climate normal = one fixed mean per field,
last season's weather. target_year is the season we are planning for (2026: the last data year is 2025).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import season_climate
from .cdl import history_token
from .ranking import FIPS, Assets, FieldContext, ROOT

CLIMATE_COLS = [
    "gdd_grow", "tmean_grow", "tmax_summer", "heat_days_32", "heat_days_35", "precip_grow", "precip_spring",
    "precip_summer", "et0_grow", "water_balance_grow", "max_dry_spell", "extreme_rain_days_spring",
    "extreme_rain_days_year", "last_spring_frost_doy", "first_fall_frost_doy", "frost_free_days",
    "srad_grow", "rh_summer",
]
SOIL_COLS = ["clay_pct", "sand_pct", "om_pct", "soc_pct", "ph_h2o", "ec_ds_m", "awc_cm_cm", "kw_factor",
             "hydgrp", "drainage_class", "texture_class"]
STATE_OF_FIPS = {v: k for k, v in FIPS.items()}


@lru_cache(maxsize=4)
def _tables(data_dir: str) -> dict:
    d = Path(data_dir)
    soil = pd.read_parquet(d / "features" / "soil.parquet").set_index("field_id")
    winter = pd.read_parquet(d / "features" / "winter_tmin.parquet").set_index("field_id")
    clim = pd.read_parquet(d / "features" / "climate_season.parquet")
    monthly = pd.read_parquet(d / "features" / "climate_monthly.parquet",
                              columns=["field_id", "month", "et0", "precip", "tmean", "heat_days_32", "frost_days", "extreme_rain_days"])
    return {
        "cells": pd.read_parquet(d / "features" / "field_cells.parquet").set_index("field_id"),
        "monthly": monthly.groupby(["field_id", "month"])[["et0", "precip", "tmean", "heat_days_32", "frost_days", "extreme_rain_days"]].mean(),
        "fields": pd.read_parquet(d / "fields" / "fields.parquet", columns=["field_id", "state_fips", "lat", "lon"]).set_index("field_id"),
        "hist": pd.read_parquet(d / "fields" / "crop_history.parquet").pivot(index="field_id", columns="year", values="cdl_code"),
        "soil": soil, "winter": winter,
        "clim": clim.set_index(["field_id", "year"]),
        "clim_norm": clim.groupby("field_id")[CLIMATE_COLS].mean(),
    }


def load_field_context(field_id: str, a: Assets, target_year: int = 2026, data_dir: str | Path = ROOT / "data",
                       scenario: tuple[float, float] = (0.0, 0.0)) -> FieldContext:
    """scenario = (temp_delta_c, precip_change_pct): the climate normal is recomputed from the shifted daily POWER data."""
    t = _tables(str(data_dir))
    cdl_to_slug = {c["cdl_code"]: s for s, c in a.candidates.items()}

    def crop_in(year: int) -> str:
        if year not in t["hist"].columns or pd.isna(t["hist"].loc[field_id, year]):
            return "unknown"
        return cdl_to_slug.get(int(t["hist"].loc[field_id, year]), "other")

    f = t["fields"].loc[field_id]
    s = t["soil"].loc[field_id]
    lag = t["clim"].loc[(field_id, target_year - 1)] if (field_id, target_year - 1) in t["clim"].index else None
    history = {int(y): cdl_to_slug.get(int(c), "other") for y, c in t["hist"].loc[field_id].items() if pd.notna(c)}
    history_rich = {int(y): history_token(c, cdl_to_slug) for y, c in t["hist"].loc[field_id].items() if pd.notna(c)}

    climate_norm = {c: float(t["clim_norm"].loc[field_id, c]) for c in CLIMATE_COLS}
    winter = float(t["winter"].loc[field_id, "winter_tmin_c"])
    m = t["monthly"].loc[field_id]
    monthly_arrays = {k: m[k].reindex(range(1, 13)).tolist() for k in ("et0", "precip", "tmean", "heat_days_32", "frost_days", "extreme_rain_days")}
    et0_monthly, precip_monthly = monthly_arrays["et0"], monthly_arrays["precip"]
    if tuple(scenario) != (0.0, 0.0):   # recompute everything from the shifted daily data
        cell = t["cells"].loc[field_id]
        daily = season_climate.shift(
            season_climate.load_daily(str(Path(data_dir) / "features" / "power_cache" / f"{cell['cell']}.json"), float(cell["cell_lat"])),
            scenario[0], scenario[1], float(cell["cell_lat"]))
        n = season_climate.normals(daily)
        climate_norm, winter = n["climate_norm"], n["winter_tmin_c"]
        et0_monthly, precip_monthly = n["et0_monthly"], n["precip_monthly"]
        monthly_arrays = {"et0": et0_monthly, "precip": precip_monthly, "tmean": n["tmean_monthly"], "heat_days_32": n["heat_days_monthly"],
                          "frost_days": n["frost_days_monthly"], "extreme_rain_days": n["extreme_rain_days_monthly"]}
    return FieldContext(
        field_id=field_id, state=STATE_OF_FIPS[f["state_fips"]], lat=float(f["lat"]), lon=float(f["lon"]),
        prev_crops=[crop_in(target_year - 1), crop_in(target_year - 2)],
        soil={c: (None if pd.isna(s[c]) else s[c]) for c in SOIL_COLS},
        slope_pct=None if pd.isna(s["slope_r"]) else float(s["slope_r"]),   # SSURGO slope until NASADEM arrives
        climate_norm=climate_norm,
        climate_lag1={c: (float(lag[c]) if lag is not None else np.nan) for c in CLIMATE_COLS},
        winter_tmin_c=winter, history=history, history_rich=history_rich, target_year=target_year,
        et0_monthly=et0_monthly, precip_monthly=precip_monthly, precip_annual=float(np.nansum(precip_monthly)),
        scenario=tuple(scenario), monthly=monthly_arrays, provenance="tables", cell=str(t["cells"].loc[field_id, "cell"]),
        area_ha=None,
    )
