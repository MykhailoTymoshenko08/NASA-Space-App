"""Build state and county boundaries for /v1/geo/* and /v1/tiles/boundaries/*.

Source: US Census Bureau TIGERweb REST service, layer group State_County (current vintage).
Docs: https://tigerweb.geo.census.gov/tigerwebmain/TIGERweb_restmapservice.html
The cartographic boundary zip downloads (www2.census.gov/geo/tiger/GENZ*) refuse non-browser
clients (HTTP 403), so we query TIGERweb and generalise server-side with maxAllowableOffset.

Town labels: TIGERweb layer group Places_CouSub_ConCity_SubMCD, "Census 2020" Incorporated Places
(the current-vintage layer has no population). Only the Census internal point is used, no outline.

Outputs (in DATA_DIR):
  states.json, counties.json   records served by /v1/geo/*
  counties.parquet             GeoParquet (EPSG:4326) for point-in-county lookups
  places.json                  incorporated places of the field states (FIELD_STATES):
                               geoid, name, state_postal, population, lat, lon
  boundaries.pmtiles           polygon layers `states` (fips,name,postal), `counties` (fips,name,state_fips)
                               and point layers for map labels:
                               `state_labels` (fips,name,postal), `county_labels` (fips,name,state_postal),
                               `places` (geoid,name,state_postal,county_fips,population)
                               `states` and `state_labels` cover CONUS. `counties`, `county_labels` and
                               `places` cover only FIELD_STATES: elsewhere the map shows just the state.
                               counties.json/parquet stay CONUS-wide (point lookups need them).

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
from shapely.ops import polylabel

from app.core.config import FIELD_STATES  # after _common: it puts backend/ on sys.path

TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer"
STATES_LAYER = 0  # "States", current vintage
COUNTIES_LAYER = 1  # "Counties", current vintage
# ~0.002 deg is ~200 m: plenty for outlines and bbox, and keeps files small.
MAX_OFFSET_DEG = 0.002

PLACES = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer"
PLACES_LAYER = 25  # "Census 2020" > "Incorporated Places": has POP100

# Zoom at which a town label first appears, by 2020 population. Towns start at county scale (7);
# smaller ones only show up closer in, so labels do not crowd the map. Largest first.
PLACE_MIN_ZOOM = [(25_000, 7), (5_000, 8), (1_000, 9), (0, 10)]


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


def fetch_records(client, url: str, where: str, fields: str) -> list[dict]:
    """Attribute rows only (no geometry), paged."""
    rows: list[dict] = []
    offset = 0
    while True:
        r = client.get(
            f"{url}/query",
            params={
                "where": where,
                "outFields": fields,
                "returnGeometry": "false",
                "resultOffset": offset,
                "resultRecordCount": 1000,
                "orderByFields": "GEOID",
                "f": "json",
            },
        )
        r.raise_for_status()
        page = r.json()
        if "error" in page:
            sys.exit(f"TIGERweb error: {page['error']}")
        batch = [f["attributes"] for f in page.get("features", [])]
        rows.extend(batch)
        if not batch or (len(batch) < 1000 and not page.get("exceededTransferLimit")):
            break
        offset += len(batch)
    return rows


def fetch_places(out) -> None:
    """Incorporated places of the field states, as label points with population."""
    states = [s for s in json.loads((out / "states.json").read_text()) if s["fips"] in FIELD_STATES]
    places = []
    with http_client() as c:
        print("fetching incorporated places from TIGERweb ...")
        for st in states:
            for r in fetch_records(
                c, f"{PLACES}/{PLACES_LAYER}", f"STATE='{st['fips']}'",
                "GEOID,BASENAME,STATE,POP100,INTPTLAT,INTPTLON",
            ):
                places.append({
                    "geoid": r["GEOID"],
                    "name": r["BASENAME"],
                    "state_postal": st["postal"],
                    "population": int(r["POP100"] or 0),
                    "lat": round(float(r["INTPTLAT"]), 5),
                    "lon": round(float(r["INTPTLON"]), 5),
                })
    places.sort(key=lambda p: p["geoid"])
    write_json(out / "places.json", places)
    print(f"  {len(places)} places -> places.json")


def label_point(geom) -> list[float]:
    """Visual centre of the largest part: the point farthest from the edge (polylabel).

    A centroid can fall outside a concave shape, and the Census internal point is often off-centre.
    """
    part = max(getattr(geom, "geoms", [geom]), key=lambda g: g.area)
    p = polylabel(part, tolerance=0.005)
    return [round(p.x, 5), round(p.y, 5)]


def centered_label_point(geom) -> list[float]:
    """State label point: the centre of the largest part as seen on the map, so the name sits in the middle.

    The centroid in Web Mercator (EPSG:3857, the map's projection), unless it falls outside the shape or
    near its edge (less than 40% of the room polylabel finds): then polylabel, as for counties.
    polylabel alone puts names in a state's widest part, e.g. low in Idaho or on the edge of Maine.
    """
    part = max(getattr(geom, "geoms", [geom]), key=lambda g: g.area)
    merc = gpd.GeoSeries([part], crs="EPSG:4326").to_crs("EPSG:3857").iloc[0]
    centre, best = merc.centroid, polylabel(merc, tolerance=500)
    room = merc.exterior.distance(best)
    p = centre if merc.contains(centre) and merc.exterior.distance(centre) >= 0.4 * room else best
    lonlat = gpd.GeoSeries([p], crs="EPSG:3857").to_crs("EPSG:4326").iloc[0]
    return [round(lonlat.x, 5), round(lonlat.y, 5)]


def place_min_zoom(population: int) -> int:
    return next(z for pop, z in PLACE_MIN_ZOOM if population >= pop)


def bbox_of(geom) -> list[float]:
    w, s, e, n = geom.bounds
    return [round(w, 5), round(s, 5), round(e, 5), round(n, 5)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--tiles-only", action="store_true", help="only rebuild boundaries.pmtiles")
    args = ap.parse_args()

    ap_tiles_only = args.tiles_only
    out = data_dir()
    states_json, counties_json = out / "states.json", out / "counties.json"
    counties_pq, tiles = out / "counties.parquet", out / "boundaries.pmtiles"

    if ap_tiles_only:
        if not (out / "places.json").exists():
            fetch_places(out)
        build_tiles(out, tiles)
        return

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
                    # Set by the app at startup: true for counties in the supported states.
                    "has_field_coverage": False,
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

    if args.force or not (out / "places.json").exists():
        fetch_places(out)

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
    # County outlines and labels only where we have fields; other states show just their name.
    co = co[co["state_fips"].isin(FIELD_STATES)]
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
    postal = dict(zip(st["fips"], st["postal"], strict=True))
    points = {name: tmp / f"{name}.geojsonl" for name in ("state_labels", "county_labels", "places")}

    def point(props: dict, lonlat: list[float], minzoom: int) -> str:
        return json.dumps({"type": "Feature", "properties": props, "tippecanoe": {"minzoom": minzoom},
                           "geometry": {"type": "Point", "coordinates": lonlat}}) + "\n"

    with points["state_labels"].open("w") as f:
        for r in st.itertuples():
            props = {"fips": r.fips, "name": r.name, "postal": r.postal}
            f.write(point(props, centered_label_point(r.geometry), 0))
    with points["county_labels"].open("w") as f:
        for r in co.itertuples():
            props = {"fips": r.fips, "name": r.name, "state_postal": postal[r.state_fips]}
            # From z5, like the county polygons: the map shows county names from 5.5, and a tall state
            # (Illinois fits at ~5.9) is drawn from z5 tiles.
            f.write(point(props, label_point(r.geometry), 5))
    field_postals = set(FIELD_STATES.values())
    places = [p for p in json.loads((out / "places.json").read_text()) if p["state_postal"] in field_postals]
    # County of each town's internal point, so the map can show only the towns of a focused county.
    pts = gpd.GeoDataFrame(
        {"i": range(len(places))},
        geometry=gpd.points_from_xy([p["lon"] for p in places], [p["lat"] for p in places]),
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(pts, co[["fips", "geometry"]], how="left", predicate="within")
    county_of = {
        i: f for i, f in joined.drop_duplicates("i").set_index("i")["fips"].items() if isinstance(f, str)
    }
    with points["places"].open("w") as f:
        for i, p in enumerate(places):
            props = {"geoid": p["geoid"], "name": p["name"], "state_postal": p["state_postal"],
                     "county_fips": county_of.get(i, ""), "population": p["population"]}
            f.write(point(props, [p["lon"], p["lat"]], place_min_zoom(p["population"])))

    layers = ["-L", f"states:{st_path}", "-L", f"counties:{co_path}"]
    for name, path in points.items():
        layers += ["-L", f"{name}:{path}"]
    attribution = "US Census Bureau TIGERweb"
    # Write next to the target, then swap it in. The API mmaps boundaries.pmtiles; overwriting the
    # file in place makes a running server read a truncated mapping and crash (SIGBUS).
    building = tiles.with_suffix(".building.pmtiles")
    run_tippecanoe([
        "-o", str(building),
        "-Z0", "-z10",
        "--name", "Field Shift boundaries",
        "--attribution", attribution,
        "--detect-shared-borders",
        "--no-tile-size-limit",
        # Keep every label point: which ones show at which zoom is set per feature (tippecanoe.minzoom).
        "-r1",
        *layers,
    ])
    building.replace(tiles)
    for p in tmp.iterdir():
        p.unlink()
    tmp.rmdir()
    print(f"wrote {tiles.name} (restart the API to serve it)")


if __name__ == "__main__":
    main()
