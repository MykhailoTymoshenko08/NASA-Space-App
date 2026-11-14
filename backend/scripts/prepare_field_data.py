"""Cut USDA Crop Sequence Boundaries (CSB) to PILOT_REGION and build field data + vector tiles.

Source: CSB 2024 as GeoParquet, Source Cooperative mirror (fiboa/vecorel "harmonized field data"):
  https://source.coop/ftw/harmonized-field-data/us_usda_cropland
  https://data.source.coop/ftw/harmonized-field-data/us_usda_cropland/latest/us_usda_cropland.parquet
Original product: https://www.nass.usda.gov/Research_and_Science/Crop-Sequence-Boundaries/
License: "License and Liability", https://gee-community-catalog.org/projects/csb/#license-and-liability

What the mirror contains (checked 2026-11-14): one edition (2024), one crop per polygon
(`crop:name`), Polygon geometries only, CRS EPSG:5070, a `bbox` covering column in metres.
It has NO multi-year crop history, so `crop_history` is written as an empty list (never guessed).
The original NASS CSB has per-year CDL codes (2017-2024); switching to it would fill history.

Steps (idempotent; use --force to rebuild):
  1. Read only the row groups whose bbox statistics overlap the pilot counties (HTTP range reads).
  2. Keep polygons whose interior point falls inside a pilot county (no duplicates across borders).
  3. field_id = "fld_" + sha1(edition + normalized WKB)[:10]; area_ha in EPSG:5070; crop_class.
  4. Write data/fields.parquet (EPSG:4326) and data/fields_meta.json.
  5. tippecanoe -> data/fields.pmtiles, layer `fields`, props field_id/crop_class/area_ha, z11..16.
"""

import argparse
import hashlib
import json
import sys

import geopandas as gpd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import shapely
from _common import data_dir, require_tippecanoe, run_tippecanoe, write_json
from _httpfile import HttpRangeFile
from pyproj import CRS

from app.core.config import get_settings

CSB_URL = (
    "https://data.source.coop/ftw/harmonized-field-data/us_usda_cropland/latest/"
    "us_usda_cropland.parquet"
)
COLUMNS = ["id", "crop:name", "metrics:area", "geometry", "bbox"]
GRID_M = 0.01  # normalise coordinates to 1 cm before hashing: ids survive float noise


def pilot_counties_5070(out) -> gpd.GeoDataFrame:
    pilot = get_settings().pilot_counties
    co = gpd.read_parquet(out / "counties.parquet")
    co = co[co["fips"].isin(pilot)]
    missing = set(pilot) - set(co["fips"])
    if missing:
        sys.exit(f"PILOT_REGION counties not in counties.parquet: {sorted(missing)}")
    return co.to_crs(5070)[["fips", "name", "state_postal", "geometry"]]


def read_pilot_rows(counties: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, str]:
    f = HttpRangeFile(CSB_URL)
    pf = pq.ParquetFile(f)
    md = pf.metadata
    geo = json.loads(md.metadata[b"geo"])
    crs = CRS.from_json_dict(geo["columns"]["geometry"]["crs"])
    if not crs.equals(CRS.from_epsg(5070), ignore_axis_order=True):
        sys.exit(f"Unexpected CSB CRS {crs.name}; update the script")
    collection = json.loads(md.metadata.get(b"collection", b"{}"))
    edition = collection.get("determination:datetime", "")[:4] or "unknown"

    w, s, e, n = counties.total_bounds
    names = [md.schema.column(i).path for i in range(md.num_columns)]
    ix = {k: names.index(f"bbox.{k}") for k in ("xmin", "ymin", "xmax", "ymax")}
    groups = []
    for i in range(md.num_row_groups):
        rg = md.row_group(i)

        def st(k, rg=rg):
            return rg.column(ix[k]).statistics

        if st("xmin").min <= e and st("xmax").max >= w and st("ymin").min <= n and st("ymax").max >= s:
            groups.append(i)
    print(f"CSB {edition}: {md.num_rows} rows, reading {len(groups)}/{md.num_row_groups} row groups")

    tables = []
    for g in groups:
        t = pf.read_row_group(g, columns=COLUMNS)
        b = t.column("bbox")
        mask = pc.and_(
            pc.and_(
                pc.less_equal(pc.struct_field(b, "xmin"), e),
                pc.greater_equal(pc.struct_field(b, "xmax"), w),
            ),
            pc.and_(
                pc.less_equal(pc.struct_field(b, "ymin"), n),
                pc.greater_equal(pc.struct_field(b, "ymax"), s),
            ),
        )
        tables.append(t.filter(mask).drop_columns(["bbox"]))
    print(f"downloaded {f.bytes_read / 1e6:.1f} MB")
    f.close()
    table = pa.concat_tables(tables)
    gdf = gpd.GeoDataFrame(
        table.drop_columns(["geometry"]).to_pandas(),
        geometry=shapely.from_wkb(table.column("geometry").to_numpy(zero_copy_only=False)),
        crs=5070,
    )
    return gdf, edition


def field_id(edition: str, geom) -> str:
    norm = shapely.normalize(shapely.set_precision(geom, GRID_M))
    h = hashlib.sha1(edition.encode() + shapely.to_wkb(norm, hex=False, output_dimension=2))
    return "fld_" + h.hexdigest()[:10]


def build_fields(out, force: bool) -> None:
    fields_pq, meta_path = out / "fields.parquet", out / "fields_meta.json"
    if fields_pq.exists() and meta_path.exists() and not force:
        print("fields.parquet exists, skipping CSB download (use --force to rebuild)")
        return

    counties = pilot_counties_5070(out)
    raw, edition = read_pilot_rows(counties)
    print(f"{len(raw)} candidate polygons in pilot bbox")

    # Split any multi-part geometry into separate fields (the contract only allows Polygon).
    raw = raw.explode(index_parts=False, ignore_index=True)
    raw = raw[raw.geometry.geom_type == "Polygon"]
    raw = raw[raw.geometry.is_valid | raw.geometry.make_valid().geom_type.eq("Polygon")]
    raw["geometry"] = raw.geometry.make_valid()
    raw = raw[raw.geometry.geom_type == "Polygon"]

    pts = gpd.GeoDataFrame(raw[[]], geometry=raw.geometry.representative_point(), crs=5070)
    joined = gpd.sjoin(pts, counties[["fips", "geometry"]], predicate="within", how="inner")
    joined = joined[~joined.index.duplicated()]
    gdf = raw.loc[joined.index].copy()
    gdf["county_fips"] = joined["fips"]

    gdf["field_id"] = [field_id(edition, g) for g in gdf.geometry]
    dup = gdf["field_id"].duplicated()
    if dup.any():
        print(f"dropping {int(dup.sum())} exact duplicate polygons")
        gdf = gdf[~dup]
    gdf["area_ha"] = (gdf.geometry.area / 10_000).round(3)
    gdf["crop_class"] = gdf["crop:name"].fillna("").astype(str)
    gdf["crop_history"] = "[]"  # mirror has a single year: see module docstring
    gdf["csb_id"] = gdf["id"].astype(str)

    out_gdf = gdf[
        ["field_id", "crop_class", "area_ha", "county_fips", "crop_history", "csb_id", "geometry"]
    ].to_crs(4326)
    out_gdf.to_parquet(fields_pq)

    per_county = out_gdf.groupby("county_fips").size().to_dict()
    pilot_key = hashlib.sha1(",".join(sorted(per_county)).encode()).hexdigest()[:6]
    meta = {
        "field_data_version": f"csb{edition}-{pilot_key}",
        "field_boundary_source": {
            "name": "USDA Crop Sequence Boundaries",
            "edition": edition,
            "estimated_csb": True,
            "attribution": (
                f"USDA NASS Crop Sequence Boundaries {edition} (algorithmic field polygons, "
                "not surveyed boundaries), via Source Cooperative / fiboa."
            ),
            "url": "https://www.nass.usda.gov/Research_and_Science/Crop-Sequence-Boundaries/",
        },
        "has_crop_history": False,
        "fields_per_county": per_county,
        "source_url": CSB_URL,
    }
    write_json(meta_path, meta)
    print(f"wrote {fields_pq.name}: {len(out_gdf)} fields {per_county}")


def build_tiles(out, force: bool) -> None:
    tiles = out / "fields.pmtiles"
    if tiles.exists() and not force:
        print("fields.pmtiles exists, skipping (use --force to rebuild)")
        return
    require_tippecanoe()
    s = get_settings()
    gdf = gpd.read_parquet(out / "fields.parquet")
    src = out / "_fields.geojsonl"
    with src.open("w") as f:
        for r in gdf.itertuples():
            props = {"field_id": r.field_id, "crop_class": r.crop_class, "area_ha": r.area_ha}
            f.write(json.dumps({"type": "Feature", "properties": props,
                                "geometry": shapely.geometry.mapping(r.geometry)}) + "\n")
    try:
        run_tippecanoe([
            "-o", str(tiles),
            "-l", "fields",
            f"-Z{s.field_tiles_min_zoom}", f"-z{s.field_tiles_max_zoom}",
            "-y", "field_id", "-y", "crop_class", "-y", "area_ha",
            "--name", "Field Shift fields",
            "--attribution", "USDA NASS Crop Sequence Boundaries",
            # Every field must be visible (and clickable) from min_zoom on: never drop features.
            "--no-feature-limit", "--no-tile-size-limit",
            "--detect-shared-borders",
            str(src),
        ])
    finally:
        src.unlink(missing_ok=True)
    print(f"wrote {tiles.name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    out = data_dir()
    if not (out / "counties.parquet").exists():
        sys.exit("counties.parquet missing: run scripts/prepare_boundaries.py first")
    build_fields(out, args.force)
    build_tiles(out, args.force)


if __name__ == "__main__":
    main()
