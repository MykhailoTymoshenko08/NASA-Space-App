"""
step 1 - sample training fields from USDA Crop Sequence Boundaries (CSB).

input:  national CSB geodatabase (e.g. NationalCSB_2018-2025_rev23 -> CSB1825.gdb)
output: data/fields/
  fields.parquet           - geoparquet, EPSG:4326, one row per field (static info + wide crop history)
  crop_history.parquet     - long table: field_id, year, cdl_code
  fields_for_gee.zip       - zipped shapefile (field_id + geometry) to upload to Google Earth Engine
  fields_for_gee.geojson   - same, as geojson

usage:
  python scripts/01_sample_csb.py --src data/raw/CSB1825.gdb --states 19 17 31 20 --n-per-state 500

how it stays light on memory:
  1. read attributes only (no geometry) for the chosen states
  2. filter + stratified sample in pandas
  3. read geometry only for the sampled rows by fid
"""

from __future__ import annotations

import argparse
import re
import shutil
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

# cdl codes that mean "cultivated land" - crops, fallow, tree crops, double crops.
# everything else (water, forest, grass/pasture, developed, wetlands) is non-crop.
CROPLAND_CODES: set[int] = set(range(1, 62)) | set(range(66, 81)) | set(range(204, 255))

# readable names for the most common codes - used only for the summary printout
CDL_NAMES = {
    1: "corn", 4: "sorghum", 5: "soybean", 21: "barley", 23: "spring_wheat",
    24: "winter_wheat", 26: "dbl_wwheat_soy", 27: "rye", 28: "oats", 36: "alfalfa",
    37: "other_hay", 61: "fallow", 176: "grass_pasture",
}

ACRES_PER_HA = 2.47105


def find_layer(src: str) -> str:
    """pick the csb feature class - named like 'national1825'."""
    layers = [name for name, _ in pyogrio.list_layers(src)]
    for name in layers:
        if name.lower().startswith("national"):
            return name
    if len(layers) == 1:
        return layers[0]
    raise SystemExit(f"can't find csb layer, available: {layers}")


def cdl_year_columns(columns: list[str]) -> list[str]:
    """CDL2018 ... CDL2025 - sorted by year."""
    cols = [c for c in columns if re.fullmatch(r"CDL\d{4}", c)]
    if not cols:
        raise SystemExit("no CDLyyyy columns found - is this a csb layer?")
    return sorted(cols)


def read_attributes(src: str, layer: str, states: list[str]) -> pd.DataFrame:
    """attributes only, filtered by state on the gdal side."""
    info = pyogrio.read_info(src, layer=layer)
    all_cols = list(info["fields"])
    cdl_cols = cdl_year_columns(all_cols)
    cols = ["CSBID", "CSBACRES", "STATEFIPS", "CNTYFIPS", "CNTY", "ASD"] + cdl_cols

    state_list = ", ".join(f"'{s}'" for s in states)
    df = pyogrio.read_dataframe(
        src,
        layer=layer,
        columns=cols,
        where=f"STATEFIPS IN ({state_list})",
        read_geometry=False,
        fid_as_index=True,  # keep gdal fid so we can fetch geometry later
    )
    print(f"read {len(df):,} csb polygons for states {states}")
    return df


def filter_fields(df: pd.DataFrame, min_acres: float, min_crop_years: int) -> pd.DataFrame:
    """keep real crop fields: big enough and cultivated most of the years."""
    cdl_cols = cdl_year_columns(list(df.columns))
    codes = df[cdl_cols].astype("Int64")

    crop_years = codes.isin(CROPLAND_CODES).sum(axis=1)
    mask = (df["CSBACRES"] >= min_acres) & (crop_years >= min_crop_years)
    out = df[mask].copy()
    print(f"after filters (>= {min_acres} ac, >= {min_crop_years} crop years): {len(out):,}")
    return out


def stratified_sample(df: pd.DataFrame, n_per_state: int, seed: int) -> pd.DataFrame:
    """same number of fields per state so one state doesn't dominate training."""
    parts = []
    for state, grp in df.groupby("STATEFIPS"):
        n = min(n_per_state, len(grp))
        if n < n_per_state:
            print(f"  state {state}: only {len(grp)} fields available, taking all")
        parts.append(grp.sample(n=n, random_state=seed))
    return pd.concat(parts)


def read_geometry(src: str, layer: str, fids: np.ndarray) -> gpd.GeoDataFrame:
    """geometry only for sampled rows."""
    gdf = pyogrio.read_dataframe(src, layer=layer, columns=["CSBID"], fids=fids)
    return gdf


def make_valid_polygons(geoms: gpd.GeoSeries) -> gpd.GeoSeries:
    """repair invalid polygons (csb has ring self-intersections from raster tracing).

    make_valid can return a geometrycollection with stray lines/points - keep polygon parts only,
    so every output geometry is a valid (multi)polygon.
    """
    fixed = []
    for g in geoms:
        if not g.is_valid:
            g = shapely.make_valid(g)
        parts = [p for p in shapely.get_parts(g) if p.geom_type in ("Polygon", "MultiPolygon")]
        polys = [q for p in parts for q in shapely.get_parts(p)]
        fixed.append(shapely.MultiPolygon(polys) if polys else g)
    return gpd.GeoSeries(fixed, index=geoms.index, crs=geoms.crs)


def build_outputs(attrs: pd.DataFrame, geom: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    cdl_cols = cdl_year_columns(list(attrs.columns))

    gdf = geom.merge(attrs.reset_index(drop=True), on="CSBID", how="inner")
    n_bad = int((~gdf.geometry.is_valid).sum())
    if n_bad:
        print(f"repairing {n_bad} invalid geometries (ring self-intersections)")
        gdf["geometry"] = make_valid_polygons(gdf.geometry)
    gdf = gdf.rename(columns={
        "CSBID": "field_id",
        "STATEFIPS": "state_fips",
        "CNTYFIPS": "county_fips",
        "CNTY": "county",
        "ASD": "asd",
    })

    # area from the source crs (albers equal area, meters) before reprojecting
    gdf["area_ha"] = (gdf.geometry.area / 10_000).round(2)
    gdf["area_ha_csb"] = (gdf["CSBACRES"] / ACRES_PER_HA).round(2)

    gdf = gdf.to_crs(epsg=4326)
    # representative_point is guaranteed to be inside the polygon (centroid may not be)
    pts = gdf.geometry.representative_point()
    gdf["lon"] = pts.x.round(6)
    gdf["lat"] = pts.y.round(6)

    # county_fips in csb is the 3-digit code - make a full 5-digit one too
    gdf["county_fips5"] = gdf["state_fips"].str.zfill(2) + gdf["county_fips"].str.zfill(3)

    # long crop history
    hist = gdf[["field_id"] + cdl_cols].melt(id_vars="field_id", var_name="col", value_name="cdl_code")
    hist["year"] = hist["col"].str[3:].astype(int)
    hist = hist.drop(columns="col").sort_values(["field_id", "year"]).reset_index(drop=True)
    hist["cdl_code"] = hist["cdl_code"].astype("Int64")

    keep = ["field_id", "state_fips", "county_fips5", "county", "asd", "area_ha", "area_ha_csb",
            "lat", "lon"] + cdl_cols + ["geometry"]
    return gdf[keep], hist


def write_gee_exports(gdf: gpd.GeoDataFrame, out_dir: Path) -> None:
    """minimal files for lina - field_id + geometry, slightly simplified to keep uploads small."""
    slim = gdf[["field_id", "geometry"]].copy()
    # ~3 m tolerance in degrees - invisible at 30 m landsat pixels
    slim["geometry"] = make_valid_polygons(slim.geometry.simplify(0.00003, preserve_topology=True))

    slim.to_file(out_dir / "fields_for_gee.geojson", driver="GeoJSON")

    shp_dir = out_dir / "fields_for_gee_shp"
    if shp_dir.exists():
        shutil.rmtree(shp_dir)
    shp_dir.mkdir()
    slim.to_file(shp_dir / "fields.shp")
    with zipfile.ZipFile(out_dir / "fields_for_gee.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for f in shp_dir.iterdir():
            zf.write(f, arcname=f.name)
    shutil.rmtree(shp_dir)


def print_summary(gdf: gpd.GeoDataFrame, hist: pd.DataFrame) -> None:
    print(f"\nsampled fields: {len(gdf):,}")
    print(gdf.groupby("state_fips").size().rename("fields").to_string())
    print(f"\narea, ha: median {gdf['area_ha'].median():.1f}, "
          f"min {gdf['area_ha'].min():.1f}, max {gdf['area_ha'].max():.1f}")

    # most common last-2-years pairs - quick sanity check for rotations
    last_two = hist.groupby("field_id")["cdl_code"].apply(lambda s: tuple(s.iloc[-2:]))
    top = last_two.value_counts().head(8)
    print("\nmost common last-2-year sequences:")
    for seq, n in top.items():
        names = " -> ".join(CDL_NAMES.get(int(c), str(c)) for c in seq)
        print(f"  {names:<30} {n}")


def main() -> None:
    p = argparse.ArgumentParser(description="sample training fields from CSB")
    p.add_argument("--src", required=True, help="path to CSB .gdb (or any ogr source with the same schema)")
    p.add_argument("--states", nargs="+", default=["19", "17", "31", "20"],
                   help="state fips codes, default: IA IL NE KS")
    p.add_argument("--n-per-state", type=int, default=500)
    p.add_argument("--min-acres", type=float, default=25.0, help="~10 ha")
    p.add_argument("--min-crop-years", type=int, default=6, help="out of 8 years in the csb window")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default="data/fields")
    args = p.parse_args()

    states = [s.zfill(2) for s in args.states]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    layer = find_layer(args.src)
    print(f"layer: {layer}")

    attrs = read_attributes(args.src, layer, states)
    attrs = filter_fields(attrs, args.min_acres, args.min_crop_years)
    sample = stratified_sample(attrs, args.n_per_state, args.seed)

    geom = read_geometry(args.src, layer, sample.index.to_numpy())
    gdf, hist = build_outputs(sample, geom)

    gdf.to_parquet(out_dir / "fields.parquet", index=False)
    hist.to_parquet(out_dir / "crop_history.parquet", index=False)
    write_gee_exports(gdf, out_dir)

    print_summary(gdf, hist)
    print(f"\nsaved to {out_dir.resolve()}")


if __name__ == "__main__":
    main()
