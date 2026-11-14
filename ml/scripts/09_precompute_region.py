"""
step 9 - precompute the features of ALL CSB fields of chosen counties, so the service answers without external calls.

for every county (5-digit FIPS, e.g. 19153 = Polk, Iowa):
  1. all CSB polygons of the county: id, acres, crop history 2018-2025, a point inside the field (WGS84), area
  2. soil at that point from USDA SDA (same code and weighting as scripts/03_soil_ssurgo.py, 25 points per query, cached)
  3. climate from NASA POWER for every grid cell the fields fall in (same cache as scripts/02): normal, last season,
     monthly profiles, winter minimum
output: data/precomputed/<county>.parquet  (columns are defined in ml_service/precomputed.py)

usage:
  python scripts/09_precompute_region.py --counties 19153
  python scripts/09_precompute_region.py --counties 19153 17113 31055 --workers 4
  python scripts/09_precompute_region.py --counties 19153 --limit 300        # quick test on the first 300 fields
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ml_service import power_client, precomputed, season_climate, soil_sda  # noqa: E402

LAYER = "national1825"
OM_TO_SOC = 1 / 1.724


def read_county(gdb: str, state: str, county: str, limit: int | None) -> pd.DataFrame:
    """all CSB polygons of one county with a representative point (inside the polygon) in WGS84."""
    cols = ["CSBID", "CSBACRES", "STATEFIPS", "CNTYFIPS"] + [f"CDL{y}" for y in precomputed.HIST_YEARS]
    attrs = pyogrio.read_dataframe(gdb, layer=LAYER, columns=cols, where=f"STATEFIPS = '{state}' AND CNTYFIPS = '{county}'",
                                   read_geometry=False, fid_as_index=True)
    if limit:
        attrs = attrs.head(limit)
    geo = pyogrio.read_dataframe(gdb, layer=LAYER, columns=["CSBID"], fids=attrs.index.to_numpy())
    area_ha = (geo.geometry.area / 10_000).round(2).to_numpy()            # source crs is equal-area, metres
    geo = geo.to_crs(epsg=4326)
    fixed = [shapely.make_valid(g) if not g.is_valid else g for g in geo.geometry]
    pts = [g.representative_point() for g in fixed]
    out = attrs.reset_index(drop=True)
    out["lat"], out["lon"], out["area_ha"] = [p.y for p in pts], [p.x for p in pts], area_ha
    return out


def soil_for(df: pd.DataFrame, workers: int) -> dict[str, dict | None]:
    """field_id -> soil dict (or None where SDA has no soil)"""
    s = soil_sda._script()
    cdir = soil_sda.cache_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    pts = df[["CSBID", "lat", "lon"]].reset_index(drop=True)
    batches = [pts.iloc[i:i + 25] for i in range(0, len(pts), 25)]
    print(f"  soil: {len(pts):,} points -> {len(batches)} queries")
    results, failed1 = s.fetch_parallel([s.mukey_sql(b) for b in batches], cdir, workers, 0.3)
    pairs = []
    for b, r in zip(batches, results):
        if r.empty:
            continue
        r = r.assign(pid=r["pid"].astype(int)).drop_duplicates("pid")
        pairs.append(pd.DataFrame({"field_id": b["CSBID"].to_numpy()[r["pid"]], "mukey": r["mukey"].to_numpy()}))
    fm = pd.concat(pairs, ignore_index=True) if pairs else pd.DataFrame(columns=["field_id", "mukey"])
    mukeys = sorted(fm["mukey"].unique())
    mb = list(s.chunks(mukeys, 40))
    print(f"  soil: {len(mukeys):,} map units -> {len(mb)} queries")
    results, failed2 = s.fetch_parallel([s.soil_sql(b) for b in mb], cdir, workers, 0.3)
    raw = pd.concat([r for r in results if not r.empty], ignore_index=True)
    mu = s.aggregate_all(raw).set_index("mukey")
    if failed1 or failed2:
        print(f"  WARNING: {failed1 + failed2} soil queries failed; rerun to fill the gaps (cached queries are skipped)")
    out: dict[str, dict | None] = {fid: None for fid in df["CSBID"]}
    for fid, mk in zip(fm["field_id"], fm["mukey"]):
        if mk in mu.index:
            d = {k: (None if pd.isna(v) else v) for k, v in mu.loc[mk].to_dict().items()}
            d["soc_pct"] = None if d.get("om_pct") is None else d["om_pct"] * OM_TO_SOC
            d["mukey"] = mk
            out[fid] = d
    return out


def climate_for(df: pd.DataFrame, workers: int) -> tuple[dict, pd.Series]:
    """cell key -> climate dict, and the cell of every field"""
    snapped = [power_client.snap_to_cell(la, lo) for la, lo in zip(df["lat"], df["lon"])]
    cells = pd.Series([power_client.cell_key(*c) for c in snapped], index=df.index)
    unique = sorted(set(snapped))
    todo = [c for c in unique if not (power_client.cache_dir() / f"{power_client.cell_key(*c)}.json").exists()]
    print(f"  climate: {len(unique)} POWER cells, {len(todo)} to download")
    if todo:
        with ThreadPoolExecutor(max_workers=min(workers, len(todo))) as pool:
            list(pool.map(lambda c: power_client.download_cell(*c), todo))
    out = {}
    for clat, clon in unique:
        key = power_client.cell_key(clat, clon)
        out[key] = season_climate.field_climate(season_climate.load_daily(str(power_client.cache_dir() / f"{key}.json"), clat),
                                                precomputed.LAST_YEAR)
    return out, cells


def build_county(gdb: str, county5: str, workers: int, limit: int | None, out_dir: Path) -> Path:
    t0 = time.time()
    state, county = county5[:2], county5[2:]
    print(f"\ncounty {county5} ({precomputed.FIPS_STATE.get(state, state)})")
    df = read_county(gdb, state, county, limit)
    print(f"  {len(df):,} CSB fields, {df['CSBACRES'].sum() * 0.404686 / 1000:.0f} thousand ha")
    soils = soil_for(df, workers)
    clim, cells = climate_for(df, workers)

    rows = []
    for i, r in df.iterrows():
        fid = str(r["CSBID"])
        meta = {"field_id": fid, "state": precomputed.FIPS_STATE.get(state, state), "county_fips5": county5,
                "lat": float(r["lat"]), "lon": float(r["lon"]), "area_ha": float(r["area_ha"]), "csb_acres": float(r["CSBACRES"])}
        hist = {y: r[f"CDL{y}"] for y in precomputed.HIST_YEARS}
        rows.append(precomputed.build_row(meta, hist, soils.get(fid), clim[cells[i]], cells[i]))
    out = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{county5}.parquet"
    out.to_parquet(path, index=False)

    no_soil = out["clay_pct"].isna().mean()
    print(f"  saved {path} ({path.stat().st_size / 1e6:.1f} MB, {len(out):,} rows) in {time.time() - t0:.0f}s")
    print(f"  fields without soil data: {no_soil:.1%} | organic soils (om > 20%): {(out['om_pct'] > 20).sum()} | "
          f"fields < 1 ha: {(out['area_ha'] < 1).sum()}")
    return path


def main() -> None:
    p = argparse.ArgumentParser(description="precompute features for whole counties")
    p.add_argument("--counties", nargs="+", required=True, help="5-digit county FIPS, e.g. 19153")
    p.add_argument("--gdb", default="data/raw/csb/CSB1825.gdb")
    p.add_argument("--out", default="data/precomputed")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=None, help="only the first N fields of each county (quick test)")
    args = p.parse_args()
    for c in args.counties:
        if len(c) != 5 or not c.isdigit():
            raise SystemExit(f"county must be a 5-digit FIPS code, got {c!r}")
        build_county(args.gdb, c, args.workers, args.limit, Path(args.out))


if __name__ == "__main__":
    main()
