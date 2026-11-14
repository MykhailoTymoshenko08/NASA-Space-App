"""Builds a FieldContext from the precomputed tables in data/ (what the service will keep for the demo region).

Same recipe as scripts/04_build_dataset.py: previous crops, climate normal = one fixed mean per field,
last season's weather. target_year is the season we are planning for (2026: the last data year is 2025).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

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
    return {
        "fields": pd.read_parquet(d / "fields" / "fields.parquet", columns=["field_id", "state_fips", "lat", "lon"]).set_index("field_id"),
        "hist": pd.read_parquet(d / "fields" / "crop_history.parquet").pivot(index="field_id", columns="year", values="cdl_code"),
        "soil": soil, "winter": winter,
        "clim": clim.set_index(["field_id", "year"]),
        "clim_norm": clim.groupby("field_id")[CLIMATE_COLS].mean(),
    }


def load_field_context(field_id: str, a: Assets, target_year: int = 2026, data_dir: str | Path = ROOT / "data") -> FieldContext:
    t = _tables(str(data_dir))
    cdl_to_slug = {c["cdl_code"]: s for s, c in a.candidates.items()}

    def crop_in(year: int) -> str:
        if year not in t["hist"].columns or pd.isna(t["hist"].loc[field_id, year]):
            return "unknown"
        return cdl_to_slug.get(int(t["hist"].loc[field_id, year]), "other")

    f = t["fields"].loc[field_id]
    s = t["soil"].loc[field_id]
    lag = t["clim"].loc[(field_id, target_year - 1)] if (field_id, target_year - 1) in t["clim"].index else None
    return FieldContext(
        field_id=field_id, state=STATE_OF_FIPS[f["state_fips"]], lat=float(f["lat"]), lon=float(f["lon"]),
        prev_crops=[crop_in(target_year - 1), crop_in(target_year - 2)],
        soil={c: (None if pd.isna(s[c]) else s[c]) for c in SOIL_COLS},
        slope_pct=None if pd.isna(s["slope_r"]) else float(s["slope_r"]),   # SSURGO slope until NASADEM arrives
        climate_norm={c: float(t["clim_norm"].loc[field_id, c]) for c in CLIMATE_COLS},
        climate_lag1={c: (float(lag[c]) if lag is not None else np.nan) for c in CLIMATE_COLS},
        winter_tmin_c=float(t["winter"].loc[field_id, "winter_tmin_c"]),
    )
