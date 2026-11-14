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


def load_ndvi_monthly(lina_dir: str | Path) -> pd.DataFrame | None:
    p = Path(lina_dir) / NDVI_FILE
    if not p.exists():
        return None
    return pd.read_csv(p, dtype={"field_id": str})


def peak_months(ndvi: pd.DataFrame, crop_of: pd.DataFrame, crop: str, default: list[int], min_rows: int = 60) -> list[int]:
    """months where the crop's mean NDVI is within 5% of its maximum (at most 3), from all fields that grew it."""
    d = ndvi.merge(crop_of, on=["field_id", "year"])
    d = d[(d["crop"] == crop) & (d["n_obs"] > 0)]
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
    months = peak_months(ndvi, crop_of, prev_crop, default)

    d = ndvi[(ndvi["year"] == last_year) & ndvi["month"].isin(months) & (ndvi["n_obs"] > 0)]
    per_field = d.groupby("field_id")["ndvi_mean"].mean().rename("v").reset_index()
    per_field = per_field.merge(crop_of[crop_of["year"] == last_year][["field_id", "crop"]], on="field_id")
    per_field = per_field[per_field["crop"] == prev_crop]
    per_field["state"] = per_field["field_id"].map(state_of)
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
