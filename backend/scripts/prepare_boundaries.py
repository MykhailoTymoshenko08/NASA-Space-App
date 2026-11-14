"""Build state and county boundaries for /v1/geo/* and /v1/tiles/boundaries/*.

Source: US Census Bureau TIGERweb REST service, layer group State_County (current vintage).
Docs: https://tigerweb.geo.census.gov/tigerwebmain/TIGERweb_restmapservice.html
The cartographic boundary zip downloads (www2.census.gov/geo/tiger/GENZ*) refuse non-browser
clients (HTTP 403), so we query TIGERweb and generalise server-side with maxAllowableOffset.

Outputs (in DATA_DIR):
  states.json, counties.json   records served by /v1/geo/*
  counties.parquet             GeoParquet (EPSG:4326) for point-in-county lookups
  boundaries.pmtiles           layers `states` (fips,name,postal) and `counties` (fips,name,state_fips)

Idempotent: re-running skips steps whose outputs exist unless --force is given.
"""

import argparse
import json
import sys

import geopandas as gpd
import pandas as pd
from _common import (
    data_dir,
    http_client,
    is_conus_state,
    require_tippecanoe,
    run_tippecanoe,
    write_json,
)
from shapely.geometry import shape

from app.core.config import get_settings

TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer"
STATES_LAYER = 0  # "States", current vintage
COUNTIES_LAYER = 1  # "Counties", current vintage
# ~0.002 deg is ~200 m: plenty for outlines and bbox, and keeps files small.
MAX_OFFSET_DEG = 0.002


def fetch_layer(client, layer: int, where: str, fields: str) -> gpd.GeoDataFrame:
    feats = []
    offset = 0
    while True:
        r = client.get(
            f"{TIGERWEB}/{layer}/query",
            params={
                "where": where,
                "outFields": fields,
                "returnGeometry": "true",
                "outSR": 4326,
                "maxAllowableOffset": MAX_OFFSET_DEG,
                "resultOffset": offset,
                "resultRecordCount": 1000,
                "orderByFields": "GEOID",
                "f": "geojson",
            },
        )
        r.raise_for_status()
        page = r.json()
        if "error" in page:
            sys.exit(f"TIGERweb error: {page['error']}")
        batch = page.get("features", [])
        feats.extend(batch)
        exceeded = page.get("exceededTransferLimit") or page.get("properties", {}).get(
            "exceededTransferLimit"
        )
        if not batch or (len(batch) < 1000 and not exceeded):
            break
        offset += len(batch)
    rows = [{**f["properties"], "geometry": shape(f["geometry"])} for f in feats]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def bbox_of(geom) -> list[float]:
    w, s, e, n = geom.bounds
    return [round(w, 5), round(s, 5), round(e, 5), round(n, 5)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    out = data_dir()
    pilot = set(get_settings().pilot_counties)
    states_json, counties_json = out / "states.json", out / "counties.json"
    counties_pq, tiles = out / "counties.parquet", out / "boundaries.pmtiles"

    if args.force or not (states_json.exists() and counties_json.exists() and counties_pq.exists()):
        with http_client() as c:
            print("fetching states from TIGERweb ...")
            st = fetch_layer(c, STATES_LAYER, "1=1", "GEOID,NAME,STUSAB,INTPTLAT,INTPTLON")
            st = st[st["GEOID"].map(is_conus_state)].copy()
            print(f"  {len(st)} CONUS states (+DC)")
            print("fetching counties from TIGERweb ...")
            parts = []
            for fips in sorted(st["GEOID"]):
                parts.append(
                    fetch_layer(
                        c, COUNTIES_LAYER, f"STATE='{fips}'",
                        "GEOID,STATE,BASENAME,NAME,INTPTLAT,INTPTLON",
                    )
                )
            co = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
            print(f"  {len(co)} counties")

        postal = dict(zip(st["GEOID"], st["STUSAB"], strict=True))
        missing = pilot - set(co["GEOID"])
        if missing:
            sys.exit(f"PILOT_REGION counties not found in TIGERweb: {sorted(missing)}")

        states = sorted(
            (
                {
                    "fips": r.GEOID,
                    "name": r.NAME,
                    "postal": r.STUSAB,
                    "bbox": bbox_of(r.geometry),
                }
                for r in st.itertuples()
            ),
            key=lambda s: s["name"],
        )
        counties = sorted(
            (
                {
                    "fips": r.GEOID,
                    "name": r.BASENAME,
                    "full_name": r.NAME,
                    "state_fips": r.STATE,
                    "state_postal": postal[r.STATE],
                    "bbox": bbox_of(r.geometry),
                    # Census internal point: always inside the county (a centroid may not be).
                    "centroid": {"lat": float(r.INTPTLAT), "lon": float(r.INTPTLON)},
                    "has_field_coverage": r.GEOID in pilot,
                }
                for r in co.itertuples()
            ),
            key=lambda c: (c["state_fips"], c["name"]),
        )
        write_json(states_json, states)
        write_json(counties_json, counties)

        gdf = co.rename(columns={"GEOID": "fips", "BASENAME": "name", "STATE": "state_fips"})
        gdf["state_postal"] = gdf["state_fips"].map(postal)
        gdf[["fips", "name", "state_fips", "state_postal", "geometry"]].to_parquet(counties_pq)
        st.rename(columns={"GEOID": "fips", "STUSAB": "postal", "NAME": "name"})[
            ["fips", "name", "postal", "geometry"]
        ].to_parquet(out / "states.parquet")
        print(f"wrote {states_json.name}, {counties_json.name}, {counties_pq.name}")
    else:
        print("boundary json/parquet exist, skipping download (use --force to rebuild)")

    if args.force or not tiles.exists():
        build_tiles(out, tiles)
    else:
        print(f"{tiles.name} exists, skipping (use --force to rebuild)")


def build_tiles(out, tiles) -> None:
    require_tippecanoe()
    tmp = out / "_tmp_boundaries"
    tmp.mkdir(exist_ok=True)
    st = gpd.read_parquet(out / "states.parquet")
    co = gpd.read_parquet(out / "counties.parquet")
    st_path, co_path = tmp / "states.geojsonl", tmp / "counties.geojsonl"
    with st_path.open("w") as f:
        for r in st.itertuples():
            props = {"fips": r.fips, "name": r.name, "postal": r.postal}
            f.write(json.dumps({"type": "Feature", "properties": props,
                                "geometry": r.geometry.__geo_interface__}) + "\n")
    with co_path.open("w") as f:
        for r in co.itertuples():
            props = {"fips": r.fips, "name": r.name, "state_fips": r.state_fips}
            # Counties are only drawn from z7, so skip them in low zooms (smaller tiles).
            f.write(json.dumps({"type": "Feature", "properties": props,
                                "tippecanoe": {"minzoom": 5},
                                "geometry": r.geometry.__geo_interface__}) + "\n")
    run_tippecanoe([
        "-o", str(tiles),
        "-Z0", "-z10",
        "--name", "Field Shift boundaries",
        "--attribution", "US Census Bureau TIGERweb",
        "--detect-shared-borders",
        "--no-tile-size-limit",
        "-L", f"states:{st_path}",
        "-L", f"counties:{co_path}",
    ])
    for p in tmp.iterdir():
        p.unlink()
    tmp.rmdir()
    print(f"wrote {tiles.name}")


if __name__ == "__main__":
    main()
