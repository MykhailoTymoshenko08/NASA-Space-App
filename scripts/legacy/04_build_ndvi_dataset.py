"""
step 4 - build the training table: one row per field x season.

inputs:
  data/fields/fields.parquet, crop_history.parquet     (step 1)
  data/features/climate_season.parquet                 (step 2)
  data/features/soil.parquet                           (step 3)
  data/lina/ndvi_season.csv    target: field_id, year, ndvi_peak, ndvi_peak_doy
  data/lina/terrain.csv        optional: field_id, slope_pct, twi
  data/lina/smap_monthly.csv   optional: field_id, year, month, smap_rootzone
  config/crop_rules.yaml       candidate crops, cdl -> slug, legume tags, organic soil limit

output: data/dataset/train_<target_source>.parquet (+ report_<target_source>.txt)
  target_source = "landsat"    real target from lina's ndvi_season.csv
  target_source = "synthetic"  target generated from a known formula (--synthetic-target). it exists only to
                               test the pipeline: the model must rediscover the formula. synthetic metrics
                               are NEVER real results - the flag is in every row and in the file name.

usage:
  python scripts/04_build_dataset.py --synthetic-target
  python scripts/04_build_dataset.py                      # real target, needs data/lina/ndvi_season.csv

target: ndvi_peak is the seasonal peak NDVI; ndvi_anom = ndvi_peak - mean ndvi_peak of the same field
(over the seasons kept in the table). the model predicts ndvi_anom, so static field differences drop out.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

LOOKBACK_LEGUME = 5   # years_since_legume is capped here ("5" means 5+ or none seen in the history we have)
CEREAL_TAG = "cereal"

# ---- synthetic target: the formula the model has to find (see synthetic_ndvi) ----
SYNTH = {
    "base_ndvi": {"corn": 0.86, "soybean": 0.83, "winter_wheat": 0.80, "oats": 0.74, "sorghum": 0.78,
                  "alfalfa": 0.84, "cereal_rye": 0.72, "field_pea": 0.72},
    "heat_sens": {"corn": 1.0, "soybean": 0.6, "winter_wheat": 0.2, "oats": 0.5, "sorghum": 0.1,
                  "alfalfa": 0.4, "cereal_rye": 0.1, "field_pea": 0.6},
    "water_sens": {"corn": 1.0, "soybean": 0.8, "winter_wheat": 0.4, "oats": 0.6, "sorghum": 0.3,
                   "alfalfa": 0.5, "cereal_rye": 0.3, "field_pea": 0.7},
    "legume_before_cereal": 0.030,       # prev crop legume, current crop cereal
    "monoculture": -0.030,               # same crop as last year
    "no_legume_4y_cereal": -0.010,       # cereal and no legume for 4+ years
    "diversity_per_crop": 0.008,         # per distinct crop above 2 in the last 4 seasons
    "heat35_per_day": -0.0025,           # x heat_days_35 anomaly (days), x heat_sens, only when hotter than normal
    "dry_per_mm": 0.00020,               # x water_balance_grow anomaly (mm), only when drier than normal,
                                         #   x water_sens x om buffer (1.6 - 0.25 * om_pct, clipped 0.6..1.6)
    "om_static": 0.010,                  # x (om_pct - 3)    static: cancels in ndvi_anom, kept for realism
    "awc_static": 0.15,                  # x (awc - 0.2)     static
    "field_sd": 0.03,                    # random field effect (static)
    "noise_sd": 0.02,
}

CLIMATE_COLS = [
    "gdd_grow", "tmean_grow", "tmax_summer", "heat_days_32", "heat_days_35", "precip_grow", "precip_spring",
    "precip_summer", "et0_grow", "water_balance_grow", "max_dry_spell", "extreme_rain_days_spring",
    "extreme_rain_days_year", "last_spring_frost_doy", "first_fall_frost_doy", "frost_free_days",
    "srad_grow", "rh_summer",
]
SOIL_COLS = ["clay_pct", "sand_pct", "om_pct", "soc_pct", "ph_h2o", "ec_ds_m", "awc_cm_cm", "kw_factor",
             "hydgrp", "drainage_class", "texture_class"]


# --------------------------------------------------------------------------- config

def load_rules(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text())
    crops = cfg["crops"]
    return {
        "candidates": list(crops),
        "cdl_to_slug": {c["cdl_code"]: slug for slug, c in crops.items()},
        "legumes": {slug for slug, c in crops.items() if "legume" in c["tags"]},
        "cereals": {slug for slug, c in crops.items() if CEREAL_TAG in c["tags"]},
        "organic_om_pct": cfg["dataset_exclusions"]["organic_soil_om_pct_above"],
    }


# --------------------------------------------------------------------------- crop features

def crop_wide(hist: pd.DataFrame, cdl_to_slug: dict) -> pd.DataFrame:
    """field x year table of crop slugs; everything outside the candidate list is 'other'."""
    h = hist.copy()
    h["crop"] = h["cdl_code"].map(cdl_to_slug).fillna("other")
    return h.pivot(index="field_id", columns="year", values="crop")


def rotation_features(wide: pd.DataFrame, years: list[int], legumes: set[str]) -> pd.DataFrame:
    """crop, previous crops and simple rotation descriptors for every field and season."""
    first_year = int(wide.columns.min())
    parts = []
    for y in years:
        crop = wide[y]
        prev1 = wide[y - 1]
        prev2 = wide[y - 2] if (y - 2) in wide.columns else pd.Series("unknown", index=wide.index)

        # years since a legume was grown, looking back from y-1 (capped)
        since = pd.Series(LOOKBACK_LEGUME, index=wide.index, dtype=float)
        for k in range(min(LOOKBACK_LEGUME, y - first_year), 0, -1):  # nearest legume wins, so go far to near
            since = since.where(~wide[y - k].isin(legumes), k)

        # distinct crops in the last 4 seasons including this one
        window = [wide[yy] for yy in range(max(first_year, y - 3), y + 1)]
        n_distinct = pd.concat(window, axis=1).nunique(axis=1)

        parts.append(pd.DataFrame({
            "field_id": wide.index, "year": y, "crop": crop.to_numpy(),
            "prev_crop_1": prev1.to_numpy(), "prev_crop_2": prev2.to_numpy(),
            "is_monoculture": ((crop == prev1) & (crop != "other")).astype(int).to_numpy(),
            "years_since_legume": since.to_numpy(),
            "n_distinct_crops_last_4": n_distinct.to_numpy(),
        }))
    return pd.concat(parts, ignore_index=True)


# --------------------------------------------------------------------------- other features

def climate_features(path: Path) -> pd.DataFrame:
    """season climate + anomaly vs the field's (= power cell's) own 2017-2025 mean."""
    c = pd.read_parquet(path)
    norm = c.groupby("field_id")[CLIMATE_COLS].transform("mean")
    anom = (c[CLIMATE_COLS] - norm).add_suffix("_anom")
    return pd.concat([c[["field_id", "year"] + CLIMATE_COLS], anom], axis=1)


def smap_features(path: Path) -> pd.DataFrame:
    """july-august mean root-zone moisture and its anomaly vs the field's own mean."""
    s = pd.read_csv(path, dtype={"field_id": str})
    s = s[s["month"].isin([7, 8])].groupby(["field_id", "year"], as_index=False)["smap_rootzone"].mean()
    s = s.rename(columns={"smap_rootzone": "smap_julaug"})
    s["smap_julaug_anom"] = s["smap_julaug"] - s.groupby("field_id")["smap_julaug"].transform("mean")
    return s


def static_features(soil_path: Path, terrain_path: Path | None) -> pd.DataFrame:
    """soil + terrain per field. slope_pct comes from lina's NASADEM file, or falls back to ssurgo slope_r."""
    s = pd.read_parquet(soil_path)[["field_id"] + SOIL_COLS + ["slope_r"]]
    s["slope_pct"], s["slope_source"], s["twi"] = s["slope_r"], "ssurgo_slope_r", np.nan
    if terrain_path is not None:
        t = pd.read_csv(terrain_path, dtype={"field_id": str}).drop_duplicates("field_id").set_index("field_id")
        has = s["field_id"].isin(t.index) & s["field_id"].map(t["slope_pct"]).notna()
        s.loc[has, "slope_pct"] = s.loc[has, "field_id"].map(t["slope_pct"])
        s.loc[has, "slope_source"] = "nasadem"
        if "twi" in t:
            s["twi"] = s["field_id"].map(t["twi"])
    return s.drop(columns="slope_r")


# --------------------------------------------------------------------------- targets

def synthetic_ndvi(df: pd.DataFrame, rng: np.random.Generator, legumes: set[str], cereals: set[str]) -> pd.Series:
    """ndvi_peak from a known formula (coefficients in SYNTH). the effects a model should find:
    previous crop (legume before cereal, monoculture, no legume for years), crop diversity, heat above normal
    (crop dependent), dry spells (crop dependent, buffered by soil organic matter)."""
    S = SYNTH
    crop = df["crop"]
    ndvi = crop.map(S["base_ndvi"]).astype(float)

    is_cereal = crop.isin(cereals)
    ndvi += np.where(df["prev_crop_1"].isin(legumes) & is_cereal, S["legume_before_cereal"], 0.0)
    ndvi += np.where(df["is_monoculture"] == 1, S["monoculture"], 0.0)
    ndvi += np.where(is_cereal & (df["years_since_legume"] >= 4), S["no_legume_4y_cereal"], 0.0)
    ndvi += S["diversity_per_crop"] * (df["n_distinct_crops_last_4"] - 2)

    hot = df["heat_days_35_anom"].clip(lower=0)
    ndvi += S["heat35_per_day"] * hot * crop.map(S["heat_sens"])

    dry = df["water_balance_grow_anom"].clip(upper=0)  # negative = drier than normal
    om_buffer = (1.6 - 0.25 * df["om_pct"]).clip(0.6, 1.6)
    ndvi += S["dry_per_mm"] * dry * crop.map(S["water_sens"]) * om_buffer

    ndvi += S["om_static"] * (df["om_pct"] - 3) + S["awc_static"] * (df["awc_cm_cm"] - 0.2)
    fields = df["field_id"].unique()
    field_effect = pd.Series(rng.normal(0, S["field_sd"], len(fields)), index=fields)
    ndvi += df["field_id"].map(field_effect)
    ndvi += rng.normal(0, S["noise_sd"], len(df))
    return ndvi.clip(0.2, 0.95)


# --------------------------------------------------------------------------- report

def build_report(df: pd.DataFrame, source: str, log: list[str]) -> str:
    lines = []
    if source == "synthetic":
        lines += ["!" * 78, "!! SYNTHETIC TARGET - pipeline test only, metrics from this table are NOT real !!", "!" * 78]
    lines += ["", *log, "", f"rows: {len(df):,}   fields: {df['field_id'].nunique():,}   "
              f"years: {df['year'].min()}-{df['year'].max()}   target_source: {source}"]

    lines += ["", "rows per year x crop:"]
    lines.append(pd.crosstab(df["year"], df["crop"], margins=True).to_string())
    lines += ["", "rows per state:", df["state_fips"].value_counts().sort_index().to_string()]

    miss = df.isna().mean()
    miss = miss[miss > 0].sort_values(ascending=False)
    lines += ["", "columns with missing values (share of rows):"]
    lines.append(miss.round(3).to_string() if len(miss) else "  none")

    lines += ["", "target:", df[["ndvi_peak", "ndvi_anom"]].describe().T[["mean", "std", "min", "50%", "max"]]
              .round(3).to_string()]
    lines += ["", "ndvi_peak by crop (mean):", df.groupby("crop")["ndvi_peak"].mean().round(3).to_string()]
    for c in ["prev_crop_1", "prev_crop_2"]:
        lines += ["", f"{c}:", df[c].value_counts().head(8).to_string()]
    lines += ["", "rotation features:",
              df[["is_monoculture", "years_since_legume", "n_distinct_crops_last_4"]].describe().T
              [["mean", "min", "50%", "max"]].round(2).to_string()]
    lines += ["", f"slope_pct source: {df['slope_source'].value_counts().to_dict()}"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- main

def main() -> None:
    p = argparse.ArgumentParser(description="build the field x year training table")
    p.add_argument("--fields", default="data/fields")
    p.add_argument("--features", default="data/features")
    p.add_argument("--lina", default="data/lina")
    p.add_argument("--rules", default="config/crop_rules.yaml")
    p.add_argument("--out", default="data/dataset")
    p.add_argument("--first-year", type=int, default=2019)
    p.add_argument("--last-year", type=int, default=2025)
    p.add_argument("--min-seasons", type=int, default=3, help="drop fields with fewer kept seasons")
    p.add_argument("--synthetic-target", action="store_true", help="generate the target from a known formula")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    fields_dir, feat_dir, lina_dir, out_dir = Path(args.fields), Path(args.features), Path(args.lina), Path(args.out)
    ndvi_path = lina_dir / "ndvi_season.csv"
    if args.synthetic_target:
        source = "synthetic"
    elif ndvi_path.exists():
        source = "landsat"
    else:
        raise SystemExit(f"{ndvi_path} not found. Wait for lina's ndvi_season.csv or run with --synthetic-target "
                         "to build a pipeline-test table.")
    rules = load_rules(Path(args.rules))
    years = list(range(args.first_year, args.last_year + 1))
    log: list[str] = []

    # ---- features
    wide = crop_wide(pd.read_parquet(fields_dir / "crop_history.parquet"), rules["cdl_to_slug"])
    df = rotation_features(wide, years, rules["legumes"])
    meta = pd.read_parquet(fields_dir / "fields.parquet", columns=["field_id", "state_fips", "lat", "lon"])
    df = df.merge(meta, on="field_id", how="left")
    df = df.merge(climate_features(feat_dir / "climate_season.parquet"), on=["field_id", "year"], how="left")
    terrain = lina_dir / "terrain.csv"
    df = df.merge(static_features(feat_dir / "soil.parquet", terrain if terrain.exists() else None),
                  on="field_id", how="left")
    smap = lina_dir / "smap_monthly.csv"
    if smap.exists():
        df = df.merge(smap_features(smap), on=["field_id", "year"], how="left")
        log.append("smap features added from lina's smap_monthly.csv")
    log.append(f"start: {len(df):,} field-seasons ({df['field_id'].nunique():,} fields x {len(years)} years)")

    # ---- filters
    n = len(df)
    df = df[df["crop"].isin(rules["candidates"])]
    log.append(f"crop is a candidate from crop_rules.yaml: -{n - len(df):,} rows (other crops, fallow, double crops)")
    n = len(df)
    df = df[~(df["om_pct"] > rules["organic_om_pct"])]
    log.append(f"organic soil (om_pct > {rules['organic_om_pct']:g}) removed: -{n - len(df):,} rows")

    # ---- target
    if source == "synthetic":
        df = df.copy()
        df["ndvi_peak"] = synthetic_ndvi(df, np.random.default_rng(args.seed), rules["legumes"], rules["cereals"])
        df["ndvi_peak_doy"] = np.nan
    else:
        nd = pd.read_csv(ndvi_path, dtype={"field_id": str})
        keep = [c for c in ["field_id", "year", "ndvi_peak", "ndvi_peak_doy"] if c in nd.columns]
        n = len(df)
        df = df.merge(nd[keep].dropna(subset=["ndvi_peak"]), on=["field_id", "year"], how="inner")
        log.append(f"has an ndvi_peak from lina: -{n - len(df):,} rows")

    n = len(df)
    df = df[df.groupby("field_id")["year"].transform("size") >= args.min_seasons]
    log.append(f"fields with >= {args.min_seasons} seasons: -{n - len(df):,} rows")
    df["ndvi_anom"] = df["ndvi_peak"] - df.groupby("field_id")["ndvi_peak"].transform("mean")
    df["target_source"] = source

    first = ["field_id", "year", "state_fips", "lat", "lon", "target_source", "ndvi_peak", "ndvi_anom", "ndvi_peak_doy"]
    df = df[first + [c for c in df.columns if c not in first]].sort_values(["field_id", "year"]).reset_index(drop=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"train_{source}.parquet"
    df.to_parquet(out_path, index=False)
    report = build_report(df, source, log)
    (out_dir / f"report_{source}.txt").write_text(report)
    if source == "synthetic":
        (out_dir / "synthetic_formula.json").write_text(json.dumps({"seed": args.seed, **SYNTH}, indent=2))
    print(report)
    print(f"\nsaved {out_path.resolve()}")


if __name__ == "__main__":
    main()
