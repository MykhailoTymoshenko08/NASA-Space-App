"""
step 4 - training table for the crop classifier: one row per field x season (2019-2025).

label:    crop         what grew on the field this season (from CSB/CDL). only the model's 5 classes
                       (config/candidate_crops.yaml, model: true); other crops are not rows
features: only what is known BEFORE sowing
  prev_crop_1/2        what grew 1 and 2 years before (non-class crops -> "other")
  norm_<weather>       the field's climate normal: one fixed mean of the POWER cell over 2017-2025
  lag1_<weather>       weather of the previous season
  soil, slope          soil.parquet (step 3); slope from lina's terrain.csv if present, else ssurgo slope_r
  lat, lon, state_fips location
  (the weather of the season itself is NOT used - the farmer does not know it when choosing the crop)
organic soils (om_pct above the limit in crop_rules.yaml) are dropped.

inputs:  data/fields/{fields,crop_history}.parquet, data/features/{climate_season,soil}.parquet,
         config/candidate_crops.yaml, config/crop_rules.yaml, data/lina/terrain.csv (optional)
output:  data/dataset/crops_train.parquet + report_crops.txt

usage:   python scripts/04_build_dataset.py

at prediction time the service feeds the same kinds of values: the cell normal (shifted by the scenario
sliders) and the last season's weather.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

CLIMATE_COLS = [
    "gdd_grow", "tmean_grow", "tmax_summer", "heat_days_32", "heat_days_35", "precip_grow", "precip_spring",
    "precip_summer", "et0_grow", "water_balance_grow", "max_dry_spell", "extreme_rain_days_spring",
    "extreme_rain_days_year", "last_spring_frost_doy", "first_fall_frost_doy", "frost_free_days",
    "srad_grow", "rh_summer",
]
SOIL_COLS = ["clay_pct", "sand_pct", "om_pct", "soc_pct", "ph_h2o", "ec_ds_m", "awc_cm_cm", "kw_factor",
             "hydgrp", "drainage_class", "texture_class"]


# --------------------------------------------------------------------------- config

def load_config(candidates_path: Path, rules_path: Path) -> tuple[dict, list[str], float]:
    """all candidates, the model's classes, organic soil limit. checks cdl codes against crop_rules.yaml."""
    cand = yaml.safe_load(candidates_path.read_text())["crops"]
    rules = yaml.safe_load(rules_path.read_text())
    for slug, c in cand.items():
        rule_crop = rules["crops"].get(slug)
        if rule_crop is None:
            raise SystemExit(f"{slug} is in candidate_crops.yaml but not in crop_rules.yaml")
        if rule_crop["cdl_code"] != c["cdl_code"]:
            raise SystemExit(f"cdl code mismatch for {slug}: {c['cdl_code']} vs {rule_crop['cdl_code']}")
    classes = [s for s, c in cand.items() if c["model"]]
    return cand, classes, rules["dataset_exclusions"]["organic_soil_om_pct_above"]


# --------------------------------------------------------------------------- crops

def crop_wide(hist: pd.DataFrame, cdl_to_slug: dict) -> pd.DataFrame:
    """field x year table of crop slugs; any crop outside the model classes becomes 'other'."""
    h = hist.copy()
    h["crop"] = h["cdl_code"].map(cdl_to_slug).fillna("other")
    return h.pivot(index="field_id", columns="year", values="crop")


def season_rows(wide: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """label and the two previous crops for every field and season. prev_crop_2 of 2019 is unknown
    (csb starts in 2018) and stays empty."""
    parts = []
    for y in years:
        parts.append(pd.DataFrame({
            "field_id": wide.index,
            "year": y,
            "crop": wide[y].to_numpy(),
            "prev_crop_1": wide[y - 1].to_numpy(),
            "prev_crop_2": wide[y - 2].to_numpy() if (y - 2) in wide.columns else None,
        }))
    return pd.concat(parts, ignore_index=True)


# --------------------------------------------------------------------------- features

def climate_features(path: Path) -> pd.DataFrame:
    """per field-year: norm_* = the field's climate normal, lag1_* = previous season.

    the normal is ONE fixed value per field (mean over all years in the file), the same in every row of
    the field. a "mean of the other years" would differ from row to row and leaks the current season:
    norm_y = (sum - x_y) / (n - 1), so x_y can be recovered from it. a constant cannot tell years apart.
    """
    c = pd.read_parquet(path)[["field_id", "year"] + CLIMATE_COLS].sort_values(["field_id", "year"])
    g = c.groupby("field_id")[CLIMATE_COLS]
    norm = g.transform("mean")
    lag = g.shift(1)
    lag = lag.where(c.groupby("field_id")["year"].diff().eq(1))       # only a real previous year, not a gap
    return pd.concat([c[["field_id", "year"]], norm.add_prefix("norm_"), lag.add_prefix("lag1_")], axis=1)


def static_features(soil_path: Path, terrain_path: Path | None) -> pd.DataFrame:
    """soil + terrain per field. slope_pct comes from lina's NASADEM file, or falls back to ssurgo slope_r."""
    s = pd.read_parquet(soil_path)[["field_id"] + SOIL_COLS + ["slope_r"]]
    s["slope_pct"], s["slope_source"], s["twi"] = s["slope_r"], "ssurgo_slope_r", np.nan
    if terrain_path is not None:
        t = pd.read_csv(terrain_path, dtype={"field_id": str}).drop_duplicates("field_id").set_index("field_id")
        has = s["field_id"].map(t["slope_pct"]).notna()
        s.loc[has, "slope_pct"] = s.loc[has, "field_id"].map(t["slope_pct"])
        s.loc[has, "slope_source"] = "nasadem"
        if "twi" in t:
            s["twi"] = s["field_id"].map(t["twi"])
    return s.drop(columns="slope_r")


# --------------------------------------------------------------------------- report

def build_report(df: pd.DataFrame, log: list[str], classes: list[str]) -> str:
    counts = df["crop"].value_counts()
    lines = [*log, "", f"rows: {len(df):,}   fields: {df['field_id'].nunique():,}   "
             f"years: {df['year'].min()}-{df['year'].max()}"]

    lines += ["", "rows per crop (label):"]
    table = pd.DataFrame({"rows": counts, "share_%": (counts / len(df) * 100).round(1),
                          "fields": df.groupby("crop")["field_id"].nunique()}).reindex(classes)
    lines.append(table.fillna(0).astype({"rows": int, "fields": int}).to_string())
    lines.append(f"majority class: {counts.index[0]} = {counts.iloc[0] / len(df):.1%} of rows")

    lines += ["", "rows per year x crop:", pd.crosstab(df["year"], df["crop"], margins=True)
              .reindex(columns=[*classes, "All"]).fillna(0).astype(int).to_string()]
    lines += ["", "rows per state x crop:", pd.crosstab(df["state_fips"], df["crop"]).reindex(columns=classes)
              .fillna(0).astype(int).to_string()]

    prev = pd.crosstab(df["prev_crop_1"], df["crop"], normalize="index").mul(100).round(0)
    lines += ["", "what grows after what, % of rows (rows = last year's crop, columns = this year's crop):",
              prev.reindex(columns=classes).fillna(0).astype(int).to_string()]

    miss = df.isna().mean()
    miss = miss[miss > 0].sort_values(ascending=False)
    lines += ["", "columns with missing values (share of rows):"]
    lines.append(miss.round(3).to_string() if len(miss) else "  none")
    lines += ["", f"slope_pct source: {df['slope_source'].value_counts().to_dict()}",
              f"feature columns: {len([c for c in df.columns if c not in ('field_id', 'year', 'crop', 'slope_source')])}"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- main

def main() -> None:
    p = argparse.ArgumentParser(description="build the crop classification table (field x year)")
    p.add_argument("--fields", default="data/fields")
    p.add_argument("--features", default="data/features")
    p.add_argument("--lina", default="data/lina")
    p.add_argument("--candidates", default="config/candidate_crops.yaml")
    p.add_argument("--rules", default="config/crop_rules.yaml")
    p.add_argument("--out", default="data/dataset")
    p.add_argument("--first-year", type=int, default=2019)
    p.add_argument("--last-year", type=int, default=2025)
    args = p.parse_args()

    fields_dir, feat_dir, out_dir = Path(args.fields), Path(args.features), Path(args.out)
    cand, classes, organic_limit = load_config(Path(args.candidates), Path(args.rules))
    years = list(range(args.first_year, args.last_year + 1))
    log: list[str] = [f"model classes: {classes}"]

    cdl_to_slug = {cand[s]["cdl_code"]: s for s in classes}
    wide = crop_wide(pd.read_parquet(fields_dir / "crop_history.parquet"), cdl_to_slug)
    df = season_rows(wide, years)
    log.append(f"start: {len(df):,} field-seasons ({df['field_id'].nunique():,} fields x {len(years)} years)")

    meta = pd.read_parquet(fields_dir / "fields.parquet", columns=["field_id", "state_fips", "lat", "lon"])
    terrain = Path(args.lina) / "terrain.csv"
    df = (df.merge(meta, on="field_id", how="left")
            .merge(climate_features(feat_dir / "climate_season.parquet"), on=["field_id", "year"], how="left")
            .merge(static_features(feat_dir / "soil.parquet", terrain if terrain.exists() else None),
                   on="field_id", how="left"))

    n = len(df)
    df = df[df["crop"].isin(classes)]
    log.append(f"label is one of the model classes: -{n - len(df):,} rows "
               "(fallow, pasture, oats, barley, rye, double crops, other)")
    n = len(df)
    df = df[~(df["om_pct"] > organic_limit)]
    log.append(f"organic soil (om_pct > {organic_limit:g}) removed: -{n - len(df):,} rows")

    first = ["field_id", "year", "state_fips", "lat", "lon", "crop", "prev_crop_1", "prev_crop_2"]
    df = df[first + [c for c in df.columns if c not in first]].sort_values(["field_id", "year"]).reset_index(drop=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / "crops_train.parquet", index=False)
    report = build_report(df, log, classes)
    (out_dir / "report_crops.txt").write_text(report)
    print(report)
    print(f"\nsaved {(out_dir / 'crops_train.parquet').resolve()}")


if __name__ == "__main__":
    main()
