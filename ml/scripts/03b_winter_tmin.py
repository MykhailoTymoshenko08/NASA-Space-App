"""
step 3b - winter minimum temperature per field, from the raw NASA POWER responses cached by step 2.

For every winter (Dec of year-1 + Jan + Feb of year) take the lowest daily T2M_MIN; the field's value is the mean of
those winter minima over the winters we have (2018-2025 -> 8 winters; the first winter, 2017, lacks its December).
Used by the winterkill rule for winter wheat (config/crop_rules.yaml, climate.winter_tmin_c).

input:  data/features/power_cache/*.json, data/features/field_cells.parquet
output: data/features/winter_tmin.parquet  (field_id, winter_tmin_c, winter_tmin_coldest_c, n_winters)

note: POWER is a 0.5 x 0.625 degree reanalysis, so its daily minima are smoother (less extreme) than a weather
station's in the same place. thresholds in the rule are set for this data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def cell_winters(path: Path) -> dict[str, float]:
    p = json.loads(path.read_text())["properties"]["parameter"]["T2M_MIN"]
    s = pd.Series(p)
    s.index = pd.to_datetime(s.index, format="%Y%m%d")
    s = s.where(s > -900)  # fill value -> nan
    s = s[s.index.month.isin([12, 1, 2])]
    winter = s.index.year + (s.index.month == 12)  # december belongs to the next year's winter
    g = s.groupby(winter)
    full = g.count() >= 85  # a complete winter has ~90 days
    return g.min()[full].to_dict()


def main() -> None:
    p = argparse.ArgumentParser(description="winter minimum temperature per field")
    p.add_argument("--features", default="data/features")
    args = p.parse_args()
    feat = Path(args.features)

    cells = pd.read_parquet(feat / "field_cells.parquet")
    per_cell = {}
    for cell in cells["cell"].unique():
        w = cell_winters(feat / "power_cache" / f"{cell}.json")
        per_cell[cell] = {"winter_tmin_c": sum(w.values()) / len(w), "winter_tmin_coldest_c": min(w.values()),
                          "n_winters": len(w)}
    out = cells[["field_id", "cell"]].merge(pd.DataFrame.from_dict(per_cell, orient="index").rename_axis("cell").reset_index(),
                                            on="cell").drop(columns="cell")
    out.round(2).to_parquet(feat / "winter_tmin.parquet", index=False)
    print(f"{len(out):,} fields, {len(per_cell)} cells, winters per cell: {sorted(out['n_winters'].unique())}")
    print(out[["winter_tmin_c", "winter_tmin_coldest_c"]].describe().T[["mean", "min", "25%", "50%", "75%", "max"]].round(1).to_string())


if __name__ == "__main__":
    main()
