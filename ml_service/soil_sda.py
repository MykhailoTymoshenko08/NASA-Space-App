"""Topsoil (0-30 cm) at a point from USDA Soil Data Access, for fields that are not precomputed.

Reuses the tested query and aggregation code of scripts/03_soil_ssurgo.py (loaded from the file, so there is one
implementation of the weighting). Answers are cached on disk like in the script.
"""
from __future__ import annotations

import importlib.util
import os
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .errors import data_unavailable

ROOT = Path(__file__).resolve().parent.parent
SDA_TIMEOUT_S = float(os.environ.get("ML_SDA_TIMEOUT_S", "8"))
OM_TO_SOC = 1 / 1.724


@lru_cache(maxsize=1)
def _script():
    spec = importlib.util.spec_from_file_location("ssurgo_script", ROOT / "scripts" / "03_soil_ssurgo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cache_dir() -> Path:
    return Path(os.environ.get("ML_SSURGO_CACHE_DIR", ROOT / "data" / "features" / "ssurgo_cache"))


def fetch_soil(lat: float, lon: float) -> dict | None:
    """soil columns as in data/features/soil.parquet (+ slope_r, mukey), or None when SDA has no soil at the point."""
    s = _script()
    cdir = cache_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    try:
        pts = pd.DataFrame({"lat": [lat], "lon": [lon]})
        ids = s.run_query(s.mukey_sql(pts), cdir, retries=2, timeout=SDA_TIMEOUT_S)
        if ids.empty:
            return None
        mukey = str(ids["mukey"].iloc[0])
        raw = s.run_query(s.soil_sql([mukey]), cdir, retries=2, timeout=SDA_TIMEOUT_S)
    except RuntimeError as exc:
        raise data_unavailable("Soil data service (USDA SDA) is not available right now.", reason=str(exc)[:120]) from exc
    if raw.empty:
        return None
    row = s.aggregate_all(raw).iloc[0].to_dict()
    row["soc_pct"] = row["om_pct"] * OM_TO_SOC if pd.notna(row["om_pct"]) else None
    row["mukey"] = mukey
    return {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in row.items()}
