"""
step 9b - polygons of the demo counties for Google Earth Engine (Lina): NDVI, SMAP and the DEM are sampled over them.

All CSB fields of the given counties (default: 19153 Polk IA and 20155 Reno KS), field_id = CSBID, EPSG:4326, made valid and
simplified like scripts/01_sample_csb.py (about 3 m tolerance, invisible at 30 m pixels).

output: data/fields/demo_fields_for_gee.zip      zipped shapefile (field_id + geometry)
        data/fields/demo_fields_for_gee.geojson  the same as geojson
usage:  python scripts/09b_export_demo_polygons.py [--counties 19153 20155]
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

ROOT = Path(__file__).resolve().parent.parent
LAYER = "national1825"


def sampler():
    """scripts/01_sample_csb.py: the same repair of invalid CSB polygons"""
    spec = importlib.util.spec_from_file_location("sample01", ROOT / "scripts" / "01_sample_csb.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def county_polygons(gdb: str, county5: str) -> gpd.GeoDataFrame:
    state, county = county5[:2], county5[2:]
    # the columns used in `where` must be read too, otherwise gdal returns nothing
    g = pyogrio.read_dataframe(gdb, layer=LAYER, columns=["CSBID", "STATEFIPS", "CNTYFIPS"],
                               where=f"STATEFIPS = '{state}' AND CNTYFIPS = '{county}'")
    g["county"] = county5
    return g.rename(columns={"CSBID": "field_id"})[["field_id", "county", "geometry"]]


def main() -> None:
    p = argparse.ArgumentParser(description="export demo-county polygons for GEE")
    p.add_argument("--counties", nargs="+", default=["19153", "20155"])
    p.add_argument("--gdb", default="data/raw/csb/CSB1825.gdb")
    p.add_argument("--out", default="data/fields")
    args = p.parse_args()

    s01 = sampler()
    parts = [county_polygons(args.gdb, c) for c in args.counties]
    gdf = pd.concat(parts, ignore_index=True)
    gdf = gdf.set_geometry("geometry").set_crs(parts[0].crs)
    gdf["geometry"] = s01.make_valid_polygons(gdf.geometry)
    gdf = gdf.to_crs(epsg=4326)
    gdf["geometry"] = s01.make_valid_polygons(gdf.geometry.simplify(0.00003, preserve_topology=True))
    assert gdf["field_id"].is_unique, "field_id (CSBID) must be unique"

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slim = gdf[["field_id", "geometry"]]
    slim.to_file(out / "demo_fields_for_gee.geojson", driver="GeoJSON")
    shp = out / "demo_fields_for_gee_shp"
    if shp.exists():
        shutil.rmtree(shp)
    shp.mkdir()
    slim.to_file(shp / "fields.shp")
    with zipfile.ZipFile(out / "demo_fields_for_gee.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for f in shp.iterdir():
            zf.write(f, arcname=f.name)
    shutil.rmtree(shp)

    print(f"{len(slim):,} fields in total")
    for c, n in gdf.groupby("county").size().items():
        print(f"  county {c}: {n:,} fields")
    print(f"invalid geometries left: {(~slim.geometry.is_valid).sum()} | empty: {slim.geometry.is_empty.sum()} | crs: {slim.crs.to_epsg()}")
    for f in ("demo_fields_for_gee.zip", "demo_fields_for_gee.geojson"):
        print(f"  {out / f}  {(out / f).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
