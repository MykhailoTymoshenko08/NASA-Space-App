"""
step 3 - soil properties from SSURGO for every sampled field, via the USDA Soil Data Access (SDA) REST API.

input:  data/fields/fields.parquet  (from step 1, uses field_id, lat, lon)
output: data/features/
  ssurgo_cache/*.json   - raw SDA responses, one file per query (re-runs are free)
  soil.parquet          - one row per field: mukey + topsoil (0-30 cm) properties

usage:
  python scripts/03_soil_ssurgo.py                 # all fields
  python scripts/03_soil_ssurgo.py --limit 100     # quick try on the first 100 fields

how it works:
  1. field point (lat/lon) -> map unit key (mukey) with SDA_Get_Mukey_from_intersection_with_WktWgs84,
     25 points per query (UNION ALL, each row tagged with a point id)
  2. unique mukeys -> components + horizons (+ representative texture), 40 mukeys per query
  3. aggregate in pandas: per component, mean over the 0-30 cm layer weighted by how much of each horizon
     falls inside the layer; then mean over components weighted by comppct_r.
     categorical columns (hydgrp, drainage class, texture) take the weighted mode.

notes:
  - a map unit can hold several soils (components); we describe the whole map unit, not one soil
  - points on water / urban land / outside the US return no mukey or no horizons -> NaN, counted in the summary
  - ssurgo gives organic matter, not carbon: soc_pct = om_pct / 1.724 (van bemmelen factor)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/tabular/post.rest"
LAYER_CM = 30.0
OM_TO_SOC = 1 / 1.724

# horizon-level numeric columns: sda name -> output name
HORIZON_VARS = {
    "claytotal_r": "clay_pct",
    "sandtotal_r": "sand_pct",
    "om_r": "om_pct",
    "ph1to1h2o_r": "ph_h2o",
    "ec_r": "ec_ds_m",
    "awc_r": "awc_cm_cm",
    "kwfact": "kw_factor",
}
NUMERIC_OUT = list(HORIZON_VARS.values()) + ["slope_r"]
CATEGORICAL_OUT = ["hydgrp", "drainage_class", "texture_class"]

RETRY_STATUS = {429, 500, 502, 503, 504}


# --------------------------------------------------------------------------- sda client

def parse_table(body: str) -> pd.DataFrame:
    """sda json -> dataframe. no rows comes back as '{}'. all values are strings."""
    data = json.loads(body)
    table = data.get("Table")
    if not table:
        return pd.DataFrame()
    return pd.DataFrame(table[1:], columns=table[0])


def run_query(sql: str, cache_dir: Path, retries: int = 5, timeout: int = 120) -> pd.DataFrame:
    """one sda query, cached on disk by the hash of the sql text.
    retries on 429/5xx/timeouts; a 400 is a bad query and fails right away."""
    key = hashlib.sha1(sql.encode()).hexdigest()[:20]
    path = cache_dir / f"{key}.json"
    if path.exists():
        return parse_table(path.read_text())

    for attempt in range(retries):
        try:
            r = requests.post(SDA_URL, json={"query": sql, "format": "JSON+COLUMNNAME"}, timeout=timeout)
            if r.status_code == 200:
                parse_table(r.text)  # make sure it parses before caching
                path.write_text(r.text)
                return parse_table(r.text)
            if r.status_code not in RETRY_STATUS:
                raise RuntimeError(f"sda {r.status_code}: {r.text[:300]!r}")
        except (requests.RequestException, json.JSONDecodeError) as e:
            print(f"    {e.__class__.__name__}, retrying")
        time.sleep(2 ** attempt * 3)
    raise RuntimeError(f"sda failed after {retries} attempts")


def mukey_sql(points: pd.DataFrame) -> str:
    """one query for several points; pid is the row position inside the batch."""
    parts = [
        f"SELECT {i} AS pid, mukey FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('POINT({lon} {lat})')"
        for i, (lat, lon) in enumerate(zip(points["lat"], points["lon"]))
    ]
    return " UNION ALL ".join(parts)


def soil_sql(mukeys: list[str]) -> str:
    """components + horizons that start above 30 cm + the representative texture of each horizon."""
    in_list = ",".join(f"'{m}'" for m in mukeys)
    return f"""
SELECT c.mukey, c.cokey, c.comppct_r, c.drainagecl, c.hydgrp, c.slope_r,
       h.chkey, h.hzdept_r, h.hzdepb_r, h.claytotal_r, h.sandtotal_r, h.om_r,
       h.ph1to1h2o_r, h.ec_r, h.awc_r, h.kwfact, t.texdesc
FROM component c
LEFT JOIN chorizon h ON h.cokey = c.cokey AND h.hzdept_r < {LAYER_CM:g}
LEFT JOIN chtexturegrp t ON t.chkey = h.chkey AND t.rvindicator = 'Yes'
WHERE c.mukey IN ({in_list})
""".strip()


def chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


# --------------------------------------------------------------------------- aggregation

def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    """weighted mean over rows where both value and weight are present."""
    ok = values.notna() & weights.notna() & (weights > 0)
    if not ok.any():
        return np.nan
    return float(np.average(values[ok], weights=weights[ok]))


def weighted_mode(values: pd.Series, weights: pd.Series):
    """category with the largest total weight (nan if there is none)."""
    ok = values.notna() & weights.notna()
    if not ok.any():
        return np.nan
    return weights[ok].groupby(values[ok]).sum().idxmax()


def aggregate_component(h: pd.DataFrame) -> dict:
    """0-30 cm layer of one component. each horizon is weighted by its thickness inside the layer."""
    h = h.dropna(subset=["chkey"]).drop_duplicates("chkey")
    overlap = (h["hzdepb_r"].clip(upper=LAYER_CM) - h["hzdept_r"].clip(lower=0)).clip(lower=0)
    out = {name: weighted_mean(h[col], overlap) for col, name in HORIZON_VARS.items()}
    # texture of the horizon that covers most of the layer
    out["texture_class"] = h.loc[overlap.idxmax(), "texdesc"] if overlap.max() > 0 else np.nan
    out["has_horizons"] = bool(overlap.max() > 0)
    return out


def aggregate_mapunit(df: pd.DataFrame) -> dict:
    """components of one map unit -> one row, weighted by comppct_r."""
    comps = []
    for cokey, g in df.groupby("cokey", sort=False):
        c = aggregate_component(g)
        c["comppct_r"] = g["comppct_r"].iloc[0]
        c["slope_r"] = g["slope_r"].iloc[0]
        c["hydgrp"] = g["hydgrp"].iloc[0]
        c["drainage_class"] = g["drainagecl"].iloc[0]
        comps.append(c)
    c = pd.DataFrame(comps)
    w = c["comppct_r"]

    out = {name: weighted_mean(c[name], w) for name in NUMERIC_OUT}
    out.update({name: weighted_mode(c[name], w) for name in CATEGORICAL_OUT})
    # share of the map unit that is real soil (has horizons) - low for water, urban land, rock outcrop
    out["mapunit_soil_pct"] = float(w[c["has_horizons"]].sum())
    return out


def aggregate_all(raw: pd.DataFrame) -> pd.DataFrame:
    num_cols = ["comppct_r", "slope_r", "hzdept_r", "hzdepb_r", *HORIZON_VARS]
    raw = raw.copy()
    raw[num_cols] = raw[num_cols].apply(pd.to_numeric, errors="coerce")
    rows = {mukey: aggregate_mapunit(g) for mukey, g in raw.groupby("mukey", sort=False)}
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("mukey").reset_index()


# --------------------------------------------------------------------------- main

def fetch_parallel(sqls: list[str], cache_dir: Path, workers: int, sleep: float) -> tuple[list[pd.DataFrame], int]:
    """run queries in parallel, keep order; failed ones give an empty frame (rerun resumes from cache)."""
    failed = 0

    def one(sql: str) -> pd.DataFrame | None:
        try:
            df = run_query(sql, cache_dir)
        except RuntimeError as e:
            print(f"    query failed: {e}")
            return None
        time.sleep(sleep)
        return df

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = []
        for n, df in enumerate(pool.map(one, sqls), start=1):
            if df is None:
                failed += 1
            results.append(df if df is not None else pd.DataFrame())
            if n % 10 == 0 or n == len(sqls):
                print(f"  {n}/{len(sqls)} queries done", flush=True)
    return results, failed


def print_summary(soil: pd.DataFrame, fields: pd.DataFrame) -> None:
    n = len(soil)
    key_cols = ["clay_pct", "om_pct", "ph_h2o", "awc_cm_cm"]
    no_mukey = soil["mukey"].isna()
    no_data = soil[key_cols].isna().all(axis=1)
    print(f"\nfields: {n:,}")
    print(f"no map unit (point outside soil survey / water): {no_mukey.sum()} ({no_mukey.mean():.1%})")
    print(f"no usable topsoil data (all of {key_cols} missing): {no_data.sum()} ({no_data.mean():.1%})")

    print("\nshare of missing values per column:")
    print(soil[NUMERIC_OUT + CATEGORICAL_OUT + ["soc_pct"]].isna().mean().round(3).to_string())

    by_state = soil.merge(fields[["field_id", "state_fips"]], on="field_id")
    by_state["no_data"] = by_state[key_cols].isna().all(axis=1)
    print("\nno-data share by state:")
    print(by_state.groupby("state_fips")["no_data"].mean().round(3).to_string())

    print("\nnumeric columns:")
    cols = NUMERIC_OUT + ["soc_pct", "mapunit_soil_pct"]
    print(soil[cols].describe().T[["count", "mean", "std", "min", "50%", "max"]].round(2).to_string())

    for c in CATEGORICAL_OUT:
        print(f"\n{c}:")
        print(soil[c].value_counts(dropna=False).head(8).to_string())


def main() -> None:
    p = argparse.ArgumentParser(description="SSURGO topsoil properties per field via USDA SDA")
    p.add_argument("--fields", default="data/fields/fields.parquet")
    p.add_argument("--out", default="data/features")
    p.add_argument("--limit", type=int, default=None, help="only the first N fields (quick test)")
    p.add_argument("--point-batch", type=int, default=25, help="points per mukey query")
    p.add_argument("--mukey-batch", type=int, default=40, help="map units per soil query")
    p.add_argument("--workers", type=int, default=4, help="parallel queries (1 = sequential)")
    p.add_argument("--sleep", type=float, default=0.5, help="pause after each query, seconds")
    args = p.parse_args()

    out_dir = Path(args.out)
    cache_dir = out_dir / "ssurgo_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    fields = pd.read_parquet(args.fields, columns=["field_id", "lat", "lon", "state_fips"])
    fields = fields.sort_values("field_id").reset_index(drop=True)
    if args.limit:
        fields = fields.head(args.limit)
    print(f"{len(fields):,} fields")

    # 1. points -> mukeys
    batches = [fields.iloc[i:i + args.point_batch] for i in range(0, len(fields), args.point_batch)]
    print(f"step 1: field points -> map units ({len(batches)} queries)")
    results, failed1 = fetch_parallel([mukey_sql(b) for b in batches], cache_dir, args.workers, args.sleep)
    pairs = []
    for batch, df in zip(batches, results):
        if df.empty:
            continue
        df["pid"] = df["pid"].astype(int)
        df = df.drop_duplicates("pid")  # a point on a boundary can hit two map units - keep the first
        pairs.append(pd.DataFrame({"field_id": batch["field_id"].to_numpy()[df["pid"]], "mukey": df["mukey"].to_numpy()}))
    field_mukey = pd.concat(pairs, ignore_index=True) if pairs else pd.DataFrame(columns=["field_id", "mukey"])
    print(f"  {len(field_mukey):,} of {len(fields):,} fields have a map unit")

    # 2. mukeys -> components + horizons
    mukeys = sorted(field_mukey["mukey"].unique())
    mbatches = list(chunks(mukeys, args.mukey_batch))
    print(f"step 2: {len(mukeys):,} unique map units -> components/horizons ({len(mbatches)} queries)")
    results, failed2 = fetch_parallel([soil_sql(b) for b in mbatches], cache_dir, args.workers, args.sleep)
    raw = pd.concat([r for r in results if not r.empty], ignore_index=True)

    # 3. aggregate and join back to fields
    print("step 3: aggregating 0-30 cm layer")
    mu = aggregate_all(raw)
    soil = fields[["field_id"]].merge(field_mukey, on="field_id", how="left").merge(mu, on="mukey", how="left")
    soil["soc_pct"] = soil["om_pct"] * OM_TO_SOC
    soil["has_data"] = soil[["clay_pct", "om_pct", "ph_h2o", "awc_cm_cm"]].notna().any(axis=1)
    soil[NUMERIC_OUT + ["soc_pct", "mapunit_soil_pct"]] = soil[NUMERIC_OUT + ["soc_pct", "mapunit_soil_pct"]].round(3)

    assert soil["field_id"].is_unique and len(soil) == len(fields)
    soil.to_parquet(out_dir / "soil.parquet", index=False)
    print_summary(soil, fields)
    if failed1 or failed2:
        print(f"\nWARNING: {failed1 + failed2} queries failed - re-run, cached queries are skipped")
    print(f"\nsaved to {(out_dir / 'soil.parquet').resolve()}")


if __name__ == "__main__":
    main()
