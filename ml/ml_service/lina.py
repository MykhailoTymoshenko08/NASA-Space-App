"""What Lina delivers (terrain, SMAP) as it reaches the service.

scripts/10_ingest_lina.py validates her CSV files and writes data/lina/derived.parquet: one row per field with
  slope_pct, twi, slope_class      NASADEM (terrain.csv)
  smap_julaug_mean, smap_deficit_share   share of years in which the Jul-Aug root-zone moisture was under the dry level
                                   of the state (the 25th percentile over all fields and years of that state)
`apply` puts them into a FieldContext, so every path (precomputed county, 2000-field tables, on the fly) gets them.
The model keeps reading the SSURGO slope it was trained on (ctx.slope_ssurgo); NASADEM slope, TWI and SMAP feed the rules,
the suitability, the erosion calculation and the data gaps.  NDVI is read at request time (ml_service/real.py, stress.py).
"""
from __future__ import annotations

import dataclasses
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .ranking import ROOT, FieldContext


def lina_dir() -> Path:
    return Path(os.environ.get("ML_LINA_DIR", ROOT / "data" / "lina"))


@lru_cache(maxsize=2)
def _read(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path).set_index("field_id")


def derived() -> pd.DataFrame | None:
    p = lina_dir() / "derived.parquet"
    return _read(str(p), p.stat().st_mtime) if p.exists() else None


def _num(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def apply(ctx: FieldContext) -> FieldContext:
    d = derived()
    if d is None or ctx.field_id not in d.index:
        return ctx
    r = d.loc[ctx.field_id]
    changes = {}
    slope, twi = _num(r.get("slope_pct")), _num(r.get("twi"))
    if slope is not None:
        changes.update(slope_pct=slope, slope_source="nasadem")
    if twi is not None:
        changes["twi"] = twi
    share = _num(r.get("smap_deficit_share"))
    if share is not None:
        changes["smap_deficit_share"] = share
    return dataclasses.replace(ctx, **changes) if changes else ctx
