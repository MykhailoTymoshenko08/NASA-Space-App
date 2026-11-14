"""
step 2 - climate features from NASA POWER (daily, AG community) for every sampled field.

input:  data/fields/fields.parquet  (from step 1)
output: data/features/
  power_cache/<cell>.json       - raw api responses, one per grid cell (re-runs are free)
  field_cells.parquet           - field_id -> power grid cell
  climate_season.parquet        - one row per field x year: growing-season features for the model
  climate_monthly.parquet       - one row per field x year x month: for the vulnerability timeline

usage:
  python scripts/02_power_climate.py --start-year 2017 --end-year 2025

why grid cells:
  POWER meteorology is on a 0.5 x 0.625 deg grid (MERRA-2). fields in the same cell get identical
  values, so we query once per cell instead of once per field - ~2000 fields become a few hundred calls.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN"]
FILL_VALUE = -999.0

LAT_STEP, LON_STEP = 0.5, 0.625

# season windows (day-of-year is fine - we only need approximate month boundaries)
GROW_MONTHS = range(4, 10)   # apr..sep
SUMMER_MONTHS = range(6, 9)  # jun..aug
SPRING_MONTHS = range(4, 7)  # apr..jun


# --------------------------------------------------------------------------- grid + fetch

def snap_to_cell(lat: float, lon: float) -> tuple[float, float]:
    """center of the merra-2 cell containing the point."""
    clat = round(lat / LAT_STEP) * LAT_STEP
    clon = round(lon / LON_STEP) * LON_STEP
    return round(clat, 4), round(clon, 4)


def cell_key(lat: float, lon: float) -> str:
    return f"{lat:+08.3f}_{lon:+09.3f}"


def fetch_cell(lat: float, lon: float, start: str, end: str, cache_dir: Path,
               retries: int = 5, timeout: int = 120) -> dict:
    """one api call per cell, cached on disk. retries with backoff on 429/5xx/timeouts."""
    path = cache_dir / f"{cell_key(lat, lon)}.json"
    if path.exists():
        return json.loads(path.read_text())

    query = {
        "parameters": ",".join(PARAMS),
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "start": start,
        "end": end,
        "format": "JSON",
        "time-standard": "LST",
    }
    for attempt in range(retries):
        try:
            r = requests.get(POWER_URL, params=query, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                path.write_text(json.dumps(data))
                return data
            # 429 = rate limit, 5xx = server busy - both worth retrying
            if r.status_code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"power {r.status_code} for {lat},{lon}: {r.text[:300]}")
        except requests.RequestException as e:
            print(f"    network error ({e.__class__.__name__}), retrying")
        time.sleep(2 ** attempt * 3)
    raise RuntimeError(f"power failed after {retries} attempts for {lat},{lon}")


def response_to_daily(data: dict, lat: float) -> pd.DataFrame:
    """power json -> daily dataframe with clean column names, fill values -> nan."""
    p = data["properties"]["parameter"]
    df = pd.DataFrame({k: pd.Series(v) for k, v in p.items()})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.replace(FILL_VALUE, np.nan).sort_index()
    df = df.rename(columns={
        "T2M": "tmean", "T2M_MAX": "tmax", "T2M_MIN": "tmin", "PRECTOTCORR": "precip",
        "RH2M": "rh", "WS2M": "wind", "ALLSKY_SFC_SW_DWN": "srad",
    })
    df["et0"] = hargreaves_et0(df["tmax"], df["tmin"], df["tmean"], df.index.dayofyear.to_numpy(), lat)
    return df


# --------------------------------------------------------------------------- agro formulas

def extraterrestrial_radiation(doy: np.ndarray, lat_deg: float) -> np.ndarray:
    """ra in mm/day of evaporation equivalent (fao-56 eq. 21, converted with 0.408)."""
    lat = math.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    decl = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(lat) * np.tan(decl), -1, 1))
    ra_mj = (24 * 60 / np.pi) * 0.0820 * dr * (
        ws * np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.sin(ws)
    )
    return 0.408 * ra_mj


def hargreaves_et0(tmax: pd.Series, tmin: pd.Series, tmean: pd.Series, doy: np.ndarray, lat: float) -> pd.Series:
    """reference evapotranspiration, mm/day (hargreaves-samani). needs only temperature,
    so it also works in climate scenarios where we shift temperature."""
    ra = extraterrestrial_radiation(doy, lat)
    trange = (tmax - tmin).clip(lower=0)
    return (0.0023 * ra * (tmean + 17.8) * np.sqrt(trange)).clip(lower=0)


def gdd(tmax: pd.Series, tmin: pd.Series, base: float = 10.0, cap: float = 30.0) -> pd.Series:
    """growing degree days, corn method (86/50 f): clip temps to [base, cap]."""
    tx = tmax.clip(lower=base, upper=cap)
    tn = tmin.clip(lower=base, upper=cap)
    return ((tx + tn) / 2 - base).clip(lower=0)


def longest_run(mask: pd.Series) -> int:
    """longest streak of True values."""
    best = cur = 0
    for v in mask.to_numpy():
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


# --------------------------------------------------------------------------- features

def season_features(daily: pd.DataFrame) -> pd.DataFrame:
    """one row per year with growing-season climate features."""
    rows = []
    for year, d in daily.groupby(daily.index.year):
        m = d.index.month
        grow, summer, spring = d[m.isin(GROW_MONTHS)], d[m.isin(SUMMER_MONTHS)], d[m.isin(SPRING_MONTHS)]
        if len(grow) < 150:  # incomplete year (e.g. current year) - skip
            continue

        # frost: last tmin < 0 before jul 1, first tmin < 0 after jul 1
        first_half = d[(d.index.month < 7) & (d["tmin"] < 0)]
        second_half = d[(d.index.month >= 7) & (d["tmin"] < 0)]
        last_spring_frost = int(first_half.index.dayofyear.max()) if len(first_half) else np.nan
        first_fall_frost = int(second_half.index.dayofyear.min()) if len(second_half) else np.nan

        precip_grow = grow["precip"].sum()
        et0_grow = grow["et0"].sum()

        rows.append({
            "year": year,
            "gdd_grow": gdd(grow["tmax"], grow["tmin"]).sum(),
            "tmean_grow": grow["tmean"].mean(),
            "tmax_summer": summer["tmax"].mean(),
            "heat_days_32": int((summer["tmax"] > 32).sum()),
            "heat_days_35": int((summer["tmax"] > 35).sum()),
            "precip_grow": precip_grow,
            "precip_spring": spring["precip"].sum(),
            "precip_summer": summer["precip"].sum(),
            "et0_grow": et0_grow,
            "water_balance_grow": precip_grow - et0_grow,
            "max_dry_spell": longest_run(d[d.index.month.isin(range(5, 9))]["precip"] < 1.0),
            "extreme_rain_days_spring": int((spring["precip"] > 25).sum()),
            "extreme_rain_days_year": int((d["precip"] > 25).sum()),
            "last_spring_frost_doy": last_spring_frost,
            "first_fall_frost_doy": first_fall_frost,
            "frost_free_days": (first_fall_frost - last_spring_frost)
                               if not (np.isnan(last_spring_frost) or np.isnan(first_fall_frost)) else np.nan,
            "srad_grow": grow["srad"].mean(),
            "rh_summer": summer["rh"].mean(),
        })
    return pd.DataFrame(rows)


def monthly_features(daily: pd.DataFrame) -> pd.DataFrame:
    """one row per year x month - feeds the vulnerability timeline and climatology normals."""
    g = daily.groupby([daily.index.year, daily.index.month])
    out = pd.DataFrame({
        "tmean": g["tmean"].mean(),
        "tmax_mean": g["tmax"].mean(),
        "tmin_mean": g["tmin"].mean(),
        "precip": g["precip"].sum(),
        "et0": g["et0"].sum(),
        "heat_days_32": g["tmax"].apply(lambda s: int((s > 32).sum())),
        "frost_days": g["tmin"].apply(lambda s: int((s < 0).sum())),
        "extreme_rain_days": g["precip"].apply(lambda s: int((s > 25).sum())),
    })
    out.index.names = ["year", "month"]
    out["water_balance"] = out["precip"] - out["et0"]
    return out.reset_index()


# --------------------------------------------------------------------------- main

def main() -> None:
    p = argparse.ArgumentParser(description="NASA POWER climate features per field")
    p.add_argument("--fields", default="data/fields/fields.parquet")
    p.add_argument("--out", default="data/features")
    p.add_argument("--start-year", type=int, default=2017, help="one year before csb start - gives lag features")
    p.add_argument("--end-year", type=int, default=2025)
    p.add_argument("--sleep", type=float, default=1.0, help="pause between api calls, seconds")
    args = p.parse_args()

    out_dir = Path(args.out)
    cache_dir = out_dir / "power_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    fields = pd.read_parquet(args.fields, columns=["field_id", "lat", "lon"])
    cells = fields.apply(lambda r: snap_to_cell(r["lat"], r["lon"]), axis=1, result_type="expand")
    fields["cell_lat"], fields["cell_lon"] = cells[0], cells[1]
    fields["cell"] = [cell_key(a, b) for a, b in zip(fields["cell_lat"], fields["cell_lon"])]
    fields[["field_id", "cell", "cell_lat", "cell_lon"]].to_parquet(out_dir / "field_cells.parquet", index=False)

    unique_cells = fields.drop_duplicates("cell")[["cell", "cell_lat", "cell_lon"]].reset_index(drop=True)
    print(f"{len(fields):,} fields -> {len(unique_cells):,} power grid cells")

    start, end = f"{args.start_year}0101", f"{args.end_year}1231"
    season_parts, monthly_parts, failed = [], [], []

    for i, c in unique_cells.iterrows():
        cached = (cache_dir / f"{c['cell']}.json").exists()
        print(f"[{i + 1}/{len(unique_cells)}] {c['cell']}{' (cache)' if cached else ''}")
        try:
            data = fetch_cell(c["cell_lat"], c["cell_lon"], start, end, cache_dir)
        except RuntimeError as e:
            print(f"    skip: {e}")
            failed.append(c["cell"])
            continue
        daily = response_to_daily(data, c["cell_lat"])

        s = season_features(daily)
        s["cell"] = c["cell"]
        season_parts.append(s)

        m = monthly_features(daily)
        m["cell"] = c["cell"]
        monthly_parts.append(m)

        if not cached:
            time.sleep(args.sleep)

    if not season_parts:
        raise SystemExit("no cells fetched - check network / api")

    season = pd.concat(season_parts, ignore_index=True)
    monthly = pd.concat(monthly_parts, ignore_index=True)

    # broadcast cell values to fields
    link = fields[["field_id", "cell"]]
    season_f = link.merge(season, on="cell").drop(columns="cell")
    monthly_f = link.merge(monthly, on="cell").drop(columns="cell")

    season_f.round(3).to_parquet(out_dir / "climate_season.parquet", index=False)
    monthly_f.round(3).to_parquet(out_dir / "climate_monthly.parquet", index=False)

    print(f"\nclimate_season:  {len(season_f):,} rows ({season_f['year'].min()}-{season_f['year'].max()})")
    print(f"climate_monthly: {len(monthly_f):,} rows")
    if failed:
        print(f"failed cells ({len(failed)}): re-run the script, cached cells are skipped")
    print(season.drop(columns="cell").describe().T[["mean", "min", "max"]].round(1).to_string())


if __name__ == "__main__":
    main()
