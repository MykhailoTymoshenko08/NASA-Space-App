"""
step 12 - choose the NDVI level for "bare soil" from the demo counties' own data.

reference classes (crop from the CSB history, NDVI from data/lina/ndvi_monthly.csv, 2018-2025):
  bare   corn / soybean / sorghum in Nov-Mar: stubble and residue, nothing growing
  green  alfalfa all year, winter wheat Nov-May, corn / soybean in Jul-Aug
for every level: share of the bare class found (NDVI under the level), share of the green class kept (NDVI at or over it),
and how often dormant winter wheat / winter alfalfa would be called bare (the false alarm that matters in Kansas).

usage: python scripts/12_check_bare_threshold.py [--out docs/ndvi_bare_threshold.txt]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ml_service import real  # noqa: E402

CDL = {1: "corn", 5: "soy", 24: "winter_wheat", 4: "sorghum", 36: "alfalfa"}
LEVELS = (0.20, 0.22, 0.25, 0.27, 0.28, 0.30, 0.32, 0.35)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/ndvi_bare_threshold.txt")
    args = ap.parse_args()
    n = real.ndvi_monthly()
    if n is None:
        sys.exit("no data/lina/ndvi_monthly.csv")
    n = n[(n.n_obs > 0) & n.year.between(2018, 2025)]
    parts = []
    for p in sorted(Path("data/precomputed").glob("*.parquet")):
        cols = ["field_id", "state"] + [f"hist_{y}" for y in range(2018, 2026)]
        d = pd.read_parquet(p, columns=cols).melt(id_vars=["field_id", "state"], var_name="v", value_name="cdl").dropna()
        d["year"] = d["v"].str[5:].astype(int)
        parts.append(d[["field_id", "state", "year", "cdl"]])
    hist = pd.concat(parts)
    hist["field_id"] = hist["field_id"].astype(str)
    hist = hist[hist["cdl"].isin(CDL)].assign(crop=lambda d: d["cdl"].map(CDL))
    x = n.assign(field_id=n["field_id"].astype(str)).merge(hist, on=["field_id", "year"])
    x["bare_ref"] = x.crop.isin(["corn", "soy", "sorghum"]) & x.month.isin([11, 12, 1, 2, 3])
    x["green_ref"] = (((x.crop == "alfalfa"))
                      | ((x.crop == "winter_wheat") & x.month.isin([11, 12, 1, 2, 3, 4, 5]))
                      | (x.crop.isin(["corn", "soy"]) & x.month.isin([7, 8])))
    out = [f"months: bare reference {int(x.bare_ref.sum()):,}, green reference {int(x.green_ref.sum()):,}; median NDVI of stubble "
           f"{x[x.bare_ref].ndvi_mean.median():.2f}, of winter wheat in Dec-Mar {x[(x.crop == 'winter_wheat') & x.month.isin([12, 1, 2, 3])].ndvi_mean.median():.2f}"]
    for st in (None, "IA", "KS"):
        g = x if st is None else x[x.state == st]
        out.append(f"\n{'IA + KS' if st is None else st}")
        out.append("  level  bare found  green kept  balanced  winter wheat (Dec-Mar) called bare  winter alfalfa called bare")
        for t in LEVELS:
            tp, tn = (g[g.bare_ref].ndvi_mean < t).mean(), (g[g.green_ref].ndvi_mean >= t).mean()
            w = (g[(g.crop == "winter_wheat") & g.month.isin([12, 1, 2, 3])].ndvi_mean < t).mean()
            a = (g[(g.crop == "alfalfa") & g.month.isin([12, 1, 2, 3])].ndvi_mean < t).mean()
            out.append(f"  {t:.2f}   {tp:9.2f}  {tn:10.2f}  {(tp + tn) / 2:8.2f}  {w:34.2f}  {a:27.2f}")
    text = "\n".join(out)
    print(text)
    Path(args.out).write_text(text + "\n")


if __name__ == "__main__":
    main()
