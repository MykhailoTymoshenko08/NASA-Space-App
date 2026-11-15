"""Last-season stress signal from Landsat NDVI (rule from Lina).

If last year's crop on the field was much greener-poorer than the same crop on neighbouring fields, repeating that crop
(or its family) is riskier and legumes / cover crops are worth more.

  1. the crop of last year; the months of its typical NDVI peak (found in the data, default months otherwise)
  2. mean NDVI of the field in those months vs the same crop, same state, same year (z-score)
  3. z below the threshold (DRAFT -1.5) -> stress, with an intensity 0.5..1 that grows as z gets lower

Needs data/lina/ndvi_monthly.csv (field_id, year, month, ndvi_mean, n_obs). Without it the signal is simply off.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

NDVI_FILE = "ndvi_monthly.csv"


@dataclass
class StressSignal:
    active: bool = False
    reason: str = "no ndvi data"
    z: float | None = None
    pct_below: float | None = None      # how far under the neighbours, %
    crop: str | None = None
    months: list[int] = field(default_factory=list)
    n_neighbors: int = 0
    intensity: float = 0.0              # 0 when off, 0.5 at the threshold, 1 from z <= threshold - 1.5


NDVI_DTYPES = {"field_id": "category", "year": "int16", "month": "int8", "ndvi_mean": "float32", "n_obs": "float32"}   # 3M rows: keep it small


def load_ndvi_monthly(lina_dir: str | Path) -> pd.DataFrame | None:
    """ndvi_monthly.parquet (what the Docker image carries) or ndvi_monthly.csv; field_id is a category so that filtering 3M rows is cheap"""
    d = Path(lina_dir)
    if (d / NDVI_FILE.replace(".csv", ".parquet")).exists():
        df = pd.read_parquet(d / NDVI_FILE.replace(".csv", ".parquet"))
    elif (d / NDVI_FILE).exists():
        df = pd.read_csv(d / NDVI_FILE, dtype=NDVI_DTYPES)
    else:
        return None
    df = df.astype({k: v for k, v in NDVI_DTYPES.items() if k in df.columns})
    df["field_id"] = df["field_id"].cat.rename_categories(lambda c: str(c))      # the csv parser makes integer categories out of the ids
    return df


def _cached(ndvi: pd.DataFrame, crop_of: pd.DataFrame, key: tuple, build):
    """the per-crop tables below are the same for every request of a year, so they are kept on crop_of (which itself is cached).
    the entry also holds the ndvi frame it was built from, so a different frame never gets a stale answer."""
    cache = crop_of.attrs.setdefault("_stress_cache", {})
    hit = cache.get(key)
    if hit is not None and hit[0] is ndvi:
        return hit[1]
    val = build()
    cache[key] = (ndvi, val)
    return val


def peak_months(ndvi: pd.DataFrame, crop_of: pd.DataFrame, crop: str, default: list[int], min_rows: int = 60) -> list[int]:
    """months where the crop's mean NDVI is within 5% of its maximum (at most 3), from all fields that grew it."""
    mine = crop_of[crop_of["crop"] == crop]
    d = ndvi[ndvi["field_id"].isin(mine["field_id"].unique()) & (ndvi["n_obs"] > 0)]
    d = d.assign(field_id=d["field_id"].astype(str)).merge(mine[["field_id", "year"]], on=["field_id", "year"])
    if len(d) < min_rows:
        return list(default)
    by_month = d.groupby("month")["ndvi_mean"].mean()
    top = by_month[by_month >= 0.95 * by_month.max()].sort_values(ascending=False).index[:3]
    return sorted(int(m) for m in top)


def compute_stress(ndvi: pd.DataFrame | None, crop_of: pd.DataFrame, state_of: pd.Series, field_id: str,
                   last_year: int, prev_crop: str | None, settings: dict) -> StressSignal:
    """crop_of: columns field_id, year, crop (slug or "other"). state_of: field_id -> state."""
    if ndvi is None or ndvi.empty:
        return StressSignal(reason="no ndvi data")
    if prev_crop in (None, "other", "unknown"):
        return StressSignal(reason="last year's crop is not a candidate crop")
    default = settings["default_peak_months"].get(prev_crop, [7, 8])
    months = _cached(ndvi, crop_of, ("peak", prev_crop), lambda: peak_months(ndvi, crop_of, prev_crop, default))

    def build():
        d = ndvi[(ndvi["year"] == last_year) & ndvi["month"].isin(months) & (ndvi["n_obs"] > 0)]
        pf = d.groupby("field_id", observed=True)["ndvi_mean"].mean().rename("v").reset_index()
        pf["field_id"] = pf["field_id"].astype(str)
        pf = pf.merge(crop_of[crop_of["year"] == last_year][["field_id", "crop"]], on="field_id")
        pf = pf[pf["crop"] == prev_crop].copy()
        pf["state"] = pf["field_id"].map(state_of)
        return pf
    per_field = _cached(ndvi, crop_of, ("field", last_year, prev_crop, tuple(months)), build)
    if field_id not in set(per_field["field_id"]):
        return StressSignal(reason="the field has no NDVI in the peak months", crop=prev_crop, months=months)
    mine = per_field[per_field["field_id"] == field_id].iloc[0]
    others = per_field[(per_field["state"] == mine["state"]) & (per_field["field_id"] != field_id)]["v"]
    if len(others) < settings["min_neighbors"]:
        return StressSignal(reason=f"only {len(others)} neighbours with the same crop", crop=prev_crop, months=months,
                            n_neighbors=len(others))
    mu, sd = float(others.mean()), max(float(others.std()), 0.02)
    z = (float(mine["v"]) - mu) / sd
    pct = 100 * (mu - float(mine["v"])) / mu
    active = z < settings["z_threshold"]
    intensity = float(np.clip((-z - abs(settings["z_threshold"])) / 1.5 + 0.5, 0.5, 1.0)) if active else 0.0
    return StressSignal(active=active, reason="stress" if active else "normal", z=round(z, 2), pct_below=round(pct, 1),
                        crop=prev_crop, months=months, n_neighbors=int(len(others)), intensity=round(intensity, 2))


def stress_multipliers(sig: StressSignal, candidates: dict, families: dict, settings: dict, lang: str) -> dict:
    """{crop: [(multiplier, text)]} for the FIRST planned year: harsher on repeating last year's crop or family,
    a bonus for legumes. empty when there is no stress."""
    if not sig.active:
        return {}
    i = sig.intensity
    pct = f"{sig.pct_below:.0f}"
    fam = {c: f for f, members in families.items() for c in members}
    out = {}
    for crop, info in candidates.items():
        if info.get("role") == "cover":
            continue
        if crop == sig.crop:
            m = 1 - settings["repeat_penalty"] * i
            text = (f"NDVI минулого сезону на {pct}% нижче за сусідів: повтор тієї ж культури ризикований (×{m:.2f})" if lang == "uk"
                    else f"last season's NDVI was {pct}% below the neighbours: repeating the same crop is risky (x{m:.2f})")
        elif fam.get(crop) and fam.get(crop) == fam.get(sig.crop):
            m = 1 - settings["family_penalty"] * i
            text = (f"NDVI минулого сезону на {pct}% нижче за сусідів: та сама родина, спільні хвороби (×{m:.2f})" if lang == "uk"
                    else f"last season's NDVI was {pct}% below the neighbours: same plant family, shared diseases (x{m:.2f})")
        elif info.get("legume"):
            m = 1 + settings["legume_bonus"] * i
            text = (f"NDVI минулого сезону на {pct}% нижче за сусідів: бобова відновлює ґрунт (×{m:.2f})" if lang == "uk"
                    else f"last season's NDVI was {pct}% below the neighbours: a legume helps the soil recover (x{m:.2f})")
        else:
            continue
        out[crop] = [(m, text)]
    return out
