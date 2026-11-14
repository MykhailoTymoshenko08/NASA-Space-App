"""Features precomputed for whole counties (scripts/09_precompute_region.py), so a request for a known field needs no
external calls. One parquet file per county in data/precomputed/, one row per CSB field.

Columns (this module is the single place that defines them; the script writes rows with `build_row`):
  field_id, state, county_fips5, lat, lon, area_ha, csb_acres, cell, mukey
  hist_2018 .. hist_2025            CDL code of every year
  clay_pct sand_pct om_pct soc_pct ph_h2o ec_ds_m awc_cm_cm kw_factor hydgrp drainage_class texture_class slope_r
  norm_<18 season features>         climate normal of the cell (2017-2025)
  lag1_<18 season features>         last season (2025)
  winter_tmin_c, precip_annual
  m_<key>                           12 monthly values: et0, precip, tmean, heat_days_32, frost_days, extreme_rain_days
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .cdl import history_token
from .ranking import ROOT, Assets, FieldContext
from .season_climate import CLIMATE_COLS

SOIL_COLS = ["clay_pct", "sand_pct", "om_pct", "soc_pct", "ph_h2o", "ec_ds_m", "awc_cm_cm", "kw_factor",
             "hydgrp", "drainage_class", "texture_class"]
MONTHLY_KEYS = ["et0", "precip", "tmean", "heat_days_32", "frost_days", "extreme_rain_days"]
HIST_YEARS = list(range(2018, 2026))
LAST_YEAR = 2025                       # the last observed season: its weather is "last season" for the 2026 plan
FIPS_STATE = {"19": "IA", "17": "IL", "20": "KS", "31": "NE"}
_MONTHLY_FROM_CLIMATE = {"et0": "et0_monthly", "precip": "precip_monthly", "tmean": "tmean_monthly",
                         "heat_days_32": "heat_days_monthly", "frost_days": "frost_days_monthly",
                         "extreme_rain_days": "extreme_rain_days_monthly"}


def directory() -> Path:
    return Path(os.environ.get("ML_PRECOMPUTED_DIR", ROOT / "data" / "precomputed"))


def build_row(meta: dict, hist: dict, soil: dict | None, climate: dict, cell: str) -> dict:
    """one parquet row. meta: field_id, state, county_fips5, lat, lon, area_ha, csb_acres. hist: {year: cdl code}.
    climate: the dict of season_climate.field_climate()."""
    row = dict(meta, cell=cell, mukey=(soil or {}).get("mukey"))
    row.update({f"hist_{y}": (int(hist[y]) if y in hist and pd.notna(hist[y]) else None) for y in HIST_YEARS})
    for c in SOIL_COLS + ["slope_r"]:
        row[c] = (soil or {}).get(c)
    row.update({f"norm_{c}": climate["climate_norm"][c] for c in CLIMATE_COLS})
    row.update({f"lag1_{c}": climate["climate_lag1"][c] for c in CLIMATE_COLS})
    row["winter_tmin_c"], row["precip_annual"] = climate["winter_tmin_c"], climate["precip_annual"]
    for k, src in _MONTHLY_FROM_CLIMATE.items():
        row[f"m_{k}"] = [float(v) for v in climate[src]]
    return row


@lru_cache(maxsize=2)
def _index(dir_: str) -> dict:
    """field_id -> row (a dict), over every county file in the directory"""
    out = {}
    for f in sorted(Path(dir_).glob("*.parquet")):
        df = pd.read_parquet(f)
        for rec in df.to_dict("records"):
            out[str(rec["field_id"])] = rec
    return out


def clear_cache() -> None:
    _index.cache_clear()


def has(field_id: str) -> bool:
    return field_id in _index(str(directory()))


def count() -> int:
    return len(_index(str(directory())))


def context(field_id: str, a: Assets, target_year: int = 2026) -> FieldContext | None:
    rec = _index(str(directory())).get(field_id)
    if rec is None:
        return None
    cdl_to_slug = {c["cdl_code"]: s for s, c in a.candidates.items()}
    codes = {y: rec[f"hist_{y}"] for y in HIST_YEARS if rec.get(f"hist_{y}") is not None and pd.notna(rec.get(f"hist_{y}"))}
    history = {y: cdl_to_slug.get(int(c), "other") for y, c in codes.items()}
    rich = {y: history_token(c, cdl_to_slug) for y, c in codes.items()}
    clean = lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else v
    soil = {c: clean(rec.get(c)) for c in SOIL_COLS}
    monthly = {k: [float(x) for x in rec[f"m_{k}"]] for k in MONTHLY_KEYS}
    return FieldContext(
        field_id=field_id, state=rec["state"], lat=float(rec["lat"]), lon=float(rec["lon"]),
        prev_crops=[history.get(target_year - 1, "unknown"), history.get(target_year - 2, "unknown")],
        soil=soil, slope_pct=clean(rec.get("slope_r")),
        climate_norm={c: float(rec[f"norm_{c}"]) for c in CLIMATE_COLS}, climate_lag1={c: float(rec[f"lag1_{c}"]) for c in CLIMATE_COLS},
        winter_tmin_c=float(rec["winter_tmin_c"]), history=history, history_rich=rich, target_year=target_year,
        et0_monthly=monthly["et0"], precip_monthly=monthly["precip"], precip_annual=float(rec["precip_annual"]),
        monthly=monthly, provenance="precomputed", cell=str(rec["cell"]), area_ha=clean(rec.get("area_ha")),
    )
