"""
step 6 - suitability trapezoids per crop and feature -> config/suitability.yaml

A trapezoid has four numbers: hard_min <= opt_min <= opt_max <= hard_max.
  1 inside the plateau [opt_min, opt_max], falls linearly to 0 at the hard bounds, 0 outside them (crop is blocked).
  a side can be open (no bound): there is no penalty on that side.
plateau = p10-p90 of the feature over the fields where the crop grew (crops_train.parquet), only for crops with at
          least MIN_FIELDS fields. otherwise the plateau is literature as well.
          BIAS CHECK: crops that only have literature plateaus (wide) could look systematically more suitable than
          crops with empirical plateaus (narrower). the script measures the mean suitability of every crop over all
          fields; if the literature-only crops come out higher by more than BIAS_MARGIN, ALL crops use the literature
          plateau, and the empirical percentiles are kept as a separate check (literature vs real sowings).
hard bounds = literature. THE LITERATURE VALUES BELOW ARE DRAFT: typed from general agronomy knowledge (FAO ECOCROP style
          ranges, Maas-Hoffman salinity thresholds), NOT yet checked against the sources. Lina confirms them (TODO).
          for EC: opt_max = ECe threshold where yield starts to fall, hard_max = ECe at 50% yield.

input:  data/dataset/crops_train.parquet, config/candidate_crops.yaml
output: config/suitability.yaml          (every value carries its own `source`)
        config/suitability_check.yaml    (real-sowing percentiles per crop and feature, never used for scoring)
        docs/suitability_literature_vs_real.md  (the table for the pitch)

usage:  python scripts/06_calibrate_thresholds.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import sys

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ml_service.ranking import trapezoid  # noqa: E402  (the same function the ranking uses)

MIN_FIELDS = 100
P_LO, P_HI = 0.10, 0.90
BIAS_MARGIN = 0.03   # DRAFT: literature-only crops may be at most 0.03 more suitable on average

# suitability name -> (column in the dataset, closed low side, closed high side, unit)
FEATURES = {
    "ph_h2o":      ("ph_h2o",          True,  True,  "pH (1:1 water)"),
    "clay_pct":    ("clay_pct",        False, True,  "% clay, 0-30 cm"),
    "soc_pct":     ("soc_pct",         True,  False, "% soil organic carbon, 0-30 cm"),
    "ec_ds_m":     ("ec_ds_m",         False, True,  "dS/m (saturated paste EC)"),
    "gdd_norm":    ("norm_gdd_grow",   True,  True,  "deg C days, Apr-Sep, base 10, normal 2017-2025"),
    "precip_norm": ("norm_precip_grow", True, True,  "mm, Apr-Sep, normal 2017-2025 (NASA POWER)"),
    "slope_pct":   ("slope_pct",       False, True,  "% slope"),
}

# DRAFT literature: (hard_min, opt_min, opt_max, hard_max), None = open side. TODO: verify (FAO ECOCROP, Maas-Hoffman)
LIT = {
    "corn":         {"ph_h2o": (5.0, 5.8, 7.5, 8.5), "clay_pct": (None, None, 40, 60), "soc_pct": (0.2, 0.9, None, None),
                     "ec_ds_m": (None, None, 1.7, 5.9), "gdd_norm": (1350, 1650, 2500, 3200),
                     "precip_norm": (300, 450, 900, 1400), "slope_pct": (None, None, 6, 25)},
    "soybean":      {"ph_h2o": (5.0, 6.0, 7.5, 8.5), "clay_pct": (None, None, 45, 65), "soc_pct": (0.2, 0.8, None, None),
                     "ec_ds_m": (None, None, 5.0, 7.5), "gdd_norm": (1300, 1600, 2500, 3200),
                     "precip_norm": (300, 420, 900, 1400), "slope_pct": (None, None, 6, 25)},
    "winter_wheat": {"ph_h2o": (5.0, 6.0, 7.5, 8.5), "clay_pct": (None, None, 45, 60), "soc_pct": (0.2, 0.8, None, None),
                     "ec_ds_m": (None, None, 6.0, 13.0), "gdd_norm": (1000, 1300, 2300, 3000),
                     "precip_norm": (200, 300, 700, 1200), "slope_pct": (None, None, 8, 30)},
    "sorghum":      {"ph_h2o": (5.0, 5.8, 8.0, 8.8), "clay_pct": (None, None, 45, 65), "soc_pct": (0.1, 0.6, None, None),
                     "ec_ds_m": (None, None, 6.8, 9.9), "gdd_norm": (1400, 1800, 2700, 3400),
                     "precip_norm": (150, 250, 700, 1200), "slope_pct": (None, None, 6, 25)},
    "alfalfa":      {"ph_h2o": (5.5, 6.5, 7.8, 8.5), "clay_pct": (None, None, 35, 50), "soc_pct": (0.2, 0.9, None, None),
                     "ec_ds_m": (None, None, 2.0, 8.8), "gdd_norm": (900, 1400, 2800, 3400),
                     "precip_norm": (250, 400, 1000, 1500), "slope_pct": (None, None, 10, 35)},
    "oats":         {"ph_h2o": (4.5, 5.5, 7.5, 8.5), "clay_pct": (None, None, 40, 60), "soc_pct": (0.2, 0.8, None, None),
                     "ec_ds_m": (None, None, 5.0, 10.0), "gdd_norm": (900, 1100, 1900, 2500),
                     "precip_norm": (250, 350, 750, 1200), "slope_pct": (None, None, 8, 30)},
    "barley":       {"ph_h2o": (5.5, 6.5, 8.0, 8.8), "clay_pct": (None, None, 35, 55), "soc_pct": (0.2, 0.8, None, None),
                     "ec_ds_m": (None, None, 8.0, 18.0), "gdd_norm": (900, 1100, 1900, 2500),
                     "precip_norm": (200, 300, 700, 1100), "slope_pct": (None, None, 8, 30)},
    "cereal_rye":   {"ph_h2o": (4.5, 5.5, 7.5, 8.5), "clay_pct": (None, None, 40, 60), "soc_pct": (0.1, 0.5, None, None),
                     "ec_ds_m": (None, None, 11.4, 16.0), "gdd_norm": (800, 1000, 2500, 3200),
                     "precip_norm": (150, 250, 800, 1300), "slope_pct": (None, None, 10, 35)},
}

HEADER = """# suitability trapezoids per crop and feature, written by scripts/06_calibrate_thresholds.py (do not edit by hand,
# rerun the script). each bound is {value, source}:
#   source "empirical p10-p90" : plateau edge = 10th / 90th percentile of the feature over fields where the crop grew
#                                 (only crops with >= @MIN_FIELDS@ fields, and only if the bias check allows it)
#   source "literature"        : DRAFT value typed from general agronomy knowledge, TODO verify against FAO ECOCROP /
#                                 Maas-Hoffman (EC). Lina confirms.
#   source "open"              : no bound on this side, no penalty there
# suitability of one feature = 1 on the plateau, linear to 0 at the hard bounds, 0 (crop blocked) outside them.
"""


def bound(value, source):
    return {"value": None if value is None else round(float(value), 3), "source": source}


def field_table(df: pd.DataFrame) -> pd.DataFrame:
    """one row per field (all fields of the dataset) with the 7 suitability inputs."""
    cols = {name: col for name, (col, *_rest) in FEATURES.items()}
    return df.drop_duplicates("field_id").set_index("field_id")[list(cols.values())].rename(columns={v: k for k, v in cols.items()})


def real_percentiles(df: pd.DataFrame, crops: list[str]) -> dict:
    """percentiles of every feature over the fields where each crop grew (a check, and the empirical plateau)."""
    out = {}
    per_field = df.drop_duplicates(["field_id", "crop"])
    for crop in crops:
        sub = per_field[per_field["crop"] == crop]
        if sub.empty:
            continue
        entry = {"n_fields": int(sub["field_id"].nunique())}
        for name, (col, *_r) in FEATURES.items():
            v = sub[col].dropna()
            entry[name] = {f"p{int(q * 100)}": round(float(v.quantile(q)), 3) for q in (0.10, 0.25, 0.50, 0.75, 0.90)}
        out[crop] = entry
    return out


def build_suitability(crops: list[str], real: dict, use_empirical: dict[str, bool]) -> dict:
    out = {}
    for crop in crops:
        use = use_empirical.get(crop, False) and crop in real
        entry = {"n_fields": real.get(crop, {}).get("n_fields", 0),
                 "plateau_source": f"empirical p{int(P_LO * 100)}-p{int(P_HI * 100)}" if use else "literature"}
        for name, (col, closed_lo, closed_hi, unit) in FEATURES.items():
            hmin, omin, omax, hmax = LIT[crop][name]
            plateau_src = entry["plateau_source"]
            if use:
                lo, hi = real[crop][name]["p10"], real[crop][name]["p90"]
                if closed_lo:
                    omin = max(lo, hmin) if hmin is not None else lo
                if closed_hi:
                    omax = min(hi, hmax) if hmax is not None else hi
            entry[name] = {
                "unit": unit,
                "hard_min": bound(hmin, "literature" if hmin is not None else "open"),
                "opt_min": bound(omin, plateau_src if omin is not None else "open"),
                "opt_max": bound(omax, plateau_src if omax is not None else "open"),
                "hard_max": bound(hmax, "literature" if hmax is not None else "open"),
            }
        out[crop] = entry
    return out


def suitability_of(fields: pd.DataFrame, entry: dict) -> pd.Series:
    """geometric mean of the trapezoids per field (0 when any feature is outside the hard bounds)."""
    vals = []
    for _, row in fields.iterrows():
        fs = [trapezoid(row[name], entry[name]) for name in FEATURES]
        fs = [f for f in fs if f is not None]
        vals.append(0.0 if (not fs or min(fs) == 0.0) else float(np.exp(np.mean(np.log(fs)))))
    return pd.Series(vals, index=fields.index)


def mean_suitability(fields: pd.DataFrame, suit: dict) -> pd.DataFrame:
    rows = {}
    for crop, entry in suit.items():
        s_ = suitability_of(fields, entry)
        rows[crop] = {"plateau": entry["plateau_source"], "mean_suitability": float(s_.mean()),
                      "share_blocked_%": float(100 * (s_ == 0).mean())}
    return pd.DataFrame(rows).T


def write_markdown(path: Path, real: dict, lit_suit: dict, fields: pd.DataFrame, table_final: pd.DataFrame,
                   table_lit: pd.DataFrame, decision: str) -> None:
    """the pitch table: literature ranges next to what farmers really sow."""
    L = ["# Literature vs real sowings", "",
         "Draft literature ranges (FAO ECOCROP style, Maas-Hoffman for salinity; **values still to be verified by Lina**) "
         "against the 10th-90th percentile of the same features over the fields where each crop really grew in Iowa, "
         "Illinois, Nebraska and Kansas (2019-2025, ~2000 fields).", "",
         "`inside plateau` = share of real fields whose value is inside the literature optimum; "
         "`inside limits` = share inside the literature hard bounds (should be close to 100%).", ""]
    per_field = fields  # field-level inputs
    for crop, rp in real.items():
        if rp["n_fields"] < 30:
            continue
        note = "" if rp["n_fields"] >= MIN_FIELDS else " (fewer than 100 fields: indicative only)"
        L += [f"## {crop} - {rp['n_fields']} fields{note}", "",
              "| feature | literature optimum | literature limits | real p10-p90 | real median | inside plateau | inside limits |",
              "|---|---|---|---|---|---|---|"]
        # fields where the crop grew
        for name in FEATURES:
            e = lit_suit[crop][name]
            hmin, omin, omax, hmax = (e[k]["value"] for k in ("hard_min", "opt_min", "opt_max", "hard_max"))
            v = FIELDS_BY_CROP[crop][name].dropna()
            inside_pl = ((v >= (omin if omin is not None else -np.inf)) & (v <= (omax if omax is not None else np.inf))).mean()
            inside_lim = ((v > (hmin if hmin is not None else -np.inf)) & (v < (hmax if hmax is not None else np.inf))).mean()
            L.append(f"| {name} | {'-' if omin is None else omin} to {'-' if omax is None else omax} | "
                     f"{'-' if hmin is None else hmin} to {'-' if hmax is None else hmax} | "
                     f"{rp[name]['p10']} to {rp[name]['p90']} | {rp[name]['p50']} | {100 * inside_pl:.0f}% | {100 * inside_lim:.0f}% |")
        L.append("")
    L += ["## Mean suitability over all fields", "", f"Decision: {decision}", "",
          "| crop | plateau used for scoring | mean suitability | fields blocked, % |", "|---|---|---|---|"]
    for crop, r in table_final.iterrows():
        L.append(f"| {crop} | {r['plateau']} | {r['mean_suitability']:.3f} | {r['share_blocked_%']:.1f} |")
    L += ["", "Same, if empirical plateaus were used for the crops that have enough fields (this is what exposed the bias):", "",
          "| crop | plateau | mean suitability | fields blocked, % |", "|---|---|---|---|"]
    for crop, r in table_lit.iterrows():
        L.append(f"| {crop} | {r['plateau']} | {r['mean_suitability']:.3f} | {r['share_blocked_%']:.1f} |")
    path.write_text("\n".join(L) + "\n")


FIELDS_BY_CROP: dict = {}


def main() -> None:
    p = argparse.ArgumentParser(description="calibrate suitability trapezoids")
    p.add_argument("--data", default="data/dataset/crops_train.parquet")
    p.add_argument("--candidates", default="config/candidate_crops.yaml")
    p.add_argument("--out", default="config/suitability.yaml")
    p.add_argument("--check-out", default="config/suitability_check.yaml")
    p.add_argument("--doc-out", default="docs/suitability_literature_vs_real.md")
    args = p.parse_args()

    crops = list(yaml.safe_load(Path(args.candidates).read_text())["crops"])
    df = pd.read_parquet(args.data)
    fields = field_table(df)
    real = real_percentiles(df, crops)
    for crop in real:   # field-level inputs of the fields where each crop grew (for the markdown table)
        ids = df.loc[df["crop"] == crop, "field_id"].unique()
        FIELDS_BY_CROP[crop] = fields.loc[ids]

    eligible = {c: real[c]["n_fields"] >= MIN_FIELDS for c in crops if c in real}
    with_emp = build_suitability(crops, real, eligible)
    all_lit = build_suitability(crops, real, {})
    t_emp, t_lit = mean_suitability(fields, with_emp), mean_suitability(fields, all_lit)

    emp_crops = [c for c in crops if eligible.get(c)]
    lit_only = [c for c in crops if not eligible.get(c)]
    gap = t_emp.loc[lit_only, "mean_suitability"].mean() - t_emp.loc[emp_crops, "mean_suitability"].mean()
    biased = gap > BIAS_MARGIN
    final, table = (all_lit, t_lit) if biased else (with_emp, t_emp)
    decision = (f"BIAS FOUND: literature-only crops {lit_only} are on average {gap:.3f} more suitable than the crops with "
                f"empirical plateaus {emp_crops} (margin {BIAS_MARGIN}). All crops use the literature plateau; "
                f"empirical percentiles are kept only as a check." if biased else
                f"no bias (gap {gap:.3f} <= {BIAS_MARGIN}); empirical p{int(P_LO * 100)}-p{int(P_HI * 100)} plateaus are used "
                f"for {emp_crops}.")

    header = HEADER.replace("@MIN_FIELDS@", str(MIN_FIELDS)) + f"# bias check: {decision}\n"
    Path(args.out).write_text(header + yaml.safe_dump(
        {"version": 1, "status": "draft", "min_fields_for_empirical": MIN_FIELDS, "plateau_mode": "literature" if biased else "empirical+literature",
         "crops": final}, sort_keys=False, allow_unicode=True, width=120))
    Path(args.check_out).write_text(
        "# percentiles of the features over fields where each crop really grew. a CHECK of the literature ranges,\n"
        "# never used for scoring. written by scripts/06_calibrate_thresholds.py\n" +
        yaml.safe_dump({"fields_in_dataset": int(len(fields)), "real_sowings": real}, sort_keys=False, allow_unicode=True))
    Path(args.doc_out).parent.mkdir(parents=True, exist_ok=True)
    write_markdown(Path(args.doc_out), real, all_lit, fields, table, t_emp, decision)

    pd.set_option("display.width", 140)
    print(f"fields in the dataset: {len(fields):,}")
    print("\nmean suitability if empirical plateaus (p10-p90) are used where there are >= 100 fields:")
    print(t_emp.round(3).to_string())
    print(f"\n{decision}")
    if biased:
        print("\nmean suitability with literature plateaus for all crops (used):")
        print(t_lit.round(3).to_string())
    print(f"\nsaved {Path(args.out).resolve()}\n      {Path(args.check_out).resolve()}\n      {Path(args.doc_out).resolve()}")


if __name__ == "__main__":
    main()
