"""Build survey townships and sections (PLSS) for /v1/tiles/plss/*.

The Public Land Survey System covers all of the field states (IA, IL, NE). A survey township is a
square of about 6 x 6 miles ("T84N R23W"), split into 36 sections of 1 square mile, numbered 1 to 36.
Farmers know them from deeds, tax statements, FSA farm maps and county plat books, so the map uses
them as the step between a county and its fields.

Sources:
  BLM National PLSS CadNSDI, layers `PLSS Township` (1) and `PLSS Section` (2):
    https://gis.blm.gov/arcgis/rest/services/Cadastral/BLM_Natl_PLSS_CadNSDI/MapServer
  Civil township names: US Census TIGERweb, Census 2020 County Subdivisions (layer 22), joined at the
  survey township's label point. Only subdivisions named "... township" are used: precincts and
  cities are not what a plat book calls the township.
  County of each label point: counties.parquet (run prepare_boundaries.py first).

Outputs (in DATA_DIR):
  plss_townships.parquet, plss_sections.parquet   download cache (EPSG:4326)
  plss.pmtiles  polygon layers `townships` (plssid, label, name, w, s, e, n) and `sections` (no props),
                label point layers `township_labels` (plssid, label, name, county_fips) and
                `section_labels` (n, county_fips). Townships from z7, sections from z11, max z12:
                sections are near-squares, so the map overzooms z12 without visible loss.

Idempotent: re-running skips steps whose outputs exist unless --force is given.
"""

import argparse
import json
import re
import sys

import geopandas as gpd
import pandas as pd
from _common import data_dir, http_client, require_tippecanoe, run_tippecanoe
from shapely.geometry import shape
from shapely.ops import polylabel

from app.core.config import FIELD_STATES  # after _common: it puts backend/ on sys.path

BLM = "https://gis.blm.gov/arcgis/rest/services/Cadastral/BLM_Natl_PLSS_CadNSDI/MapServer"
TOWNSHIP_LAYER, SECTION_LAYER = 1, 2
BLM_PAGE = 2000  # the service's maxRecordCount
COUSUB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/22"
# ~0.0001 deg is ~10 m: section lines stay on the roads that usually run along them.
PLSS_OFFSET_DEG = 0.0001
COUSUB_OFFSET_DEG = 0.001

TOWNSHIP_MIN_ZOOM, SECTION_MIN_ZOOM, MAX_ZOOM = 7, 11, 12


def fetch(client, url: str, where: str, fields: str, offset_deg: float, page: int) -> gpd.GeoDataFrame:
    """All features of an ArcGIS layer as GeoJSON, paged."""
    feats: list[dict] = []
    start = 0
    while True:
        r = client.get(
            f"{url}/query",
            params={
                "where": where,
                "outFields": fields,
                "returnGeometry": "true",
                "outSR": 4326,
                "maxAllowableOffset": offset_deg,
                "resultOffset": start,
                "resultRecordCount": page,
                "orderByFields": "OBJECTID",
                "f": "geojson",
            },
        )
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            sys.exit(f"ArcGIS error from {url}: {body['error']}")
        batch = body.get("features", [])
        feats.extend(f for f in batch if f.get("geometry"))
        props = body.get("properties", {})
        exceeded = body.get("exceededTransferLimit") or props.get("exceededTransferLimit")
        if not batch or (len(batch) < page and not exceeded):
            break
        start += len(batch)
    rows = [{**f["properties"], "geometry": shape(f["geometry"])} for f in feats]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def label_point(geom, tolerance: float) -> tuple[float, float]:
    """Visual centre of the largest part (polylabel): inside the shape even when it is not square."""
    part = max(getattr(geom, "geoms", [geom]), key=lambda g: g.area)
    p = polylabel(part, tolerance=tolerance)
    return round(p.x, 5), round(p.y, 5)


def civil_name(cousub_name: str) -> str:
    """'Grant township' -> 'Grant Twp'; anything else (precinct, city) -> ''."""
    suffix = " township"
    if not cousub_name.lower().endswith(suffix):
        return ""
    return cousub_name[: -len(suffix)].strip() + " Twp"


def township_label(raw: str) -> str:
    """BLM gives '80N 24W' for most townships and 'T85N R47W' for a few: always 'T80N R24W'."""
    m = re.fullmatch(r"T?(\d+)\s*([NS])\s+R?(\d+)\s*([EW])", raw.strip())
    return f"T{m[1]}{m[2]} R{m[3]}{m[4]}" if m else raw.strip()


def section_number(v) -> int | None:
    s = str(v or "").strip()
    return int(s) if s.isdigit() and 1 <= int(s) <= 36 else None


def download(out, force: bool) -> None:
    tw_pq, sec_pq = out / "plss_townships.parquet", out / "plss_sections.parquet"
    if not force and tw_pq.exists() and sec_pq.exists():
        print("PLSS parquet exists, skipping download (use --force to refetch)")
        return
    postals = sorted(FIELD_STATES.values())
    with http_client() as c:
        tws, secs, subs = [], [], []
        for postal in postals:
            print(f"fetching {postal} survey townships from BLM ...")
            tws.append(fetch(c, f"{BLM}/{TOWNSHIP_LAYER}", f"STATEABBR='{postal}'",
                             "PLSSID,TWNSHPLAB", PLSS_OFFSET_DEG, BLM_PAGE))
            print(f"fetching {postal} sections from BLM ...")
            # PLSSID starts with the state postal code (e.g. IA050850N0470W0).
            secs.append(fetch(c, f"{BLM}/{SECTION_LAYER}", f"PLSSID LIKE '{postal}%'",
                              "PLSSID,FRSTDIVNO,FRSTDIVTYP", PLSS_OFFSET_DEG, BLM_PAGE))
            print(f"  {len(tws[-1])} townships, {len(secs[-1])} sections")
        for fips in sorted(FIELD_STATES):
            print(f"fetching county subdivisions of state {fips} from TIGERweb ...")
            subs.append(fetch(c, COUSUB, f"STATE='{fips}'", "GEOID,NAME", COUSUB_OFFSET_DEG, 1000))
    tw = gpd.GeoDataFrame(pd.concat(tws, ignore_index=True), crs="EPSG:4326")
    sec = gpd.GeoDataFrame(pd.concat(secs, ignore_index=True), crs="EPSG:4326")
    sub = gpd.GeoDataFrame(pd.concat(subs, ignore_index=True), crs="EPSG:4326")
    if tw.empty or sec.empty:
        sys.exit("BLM returned no townships or sections")

    tw = tw.rename(columns={"PLSSID": "plssid", "TWNSHPLAB": "label"})
    tw["label"] = tw["label"].fillna("").str.strip()
    tw = tw.dissolve(by="plssid", as_index=False, aggfunc="first")  # one row per township
    pts = [label_point(g, 0.001) for g in tw.geometry]
    tw["lx"], tw["ly"] = [p[0] for p in pts], [p[1] for p in pts]
    lp = gpd.GeoDataFrame(
        {"i": range(len(tw))}, geometry=gpd.points_from_xy(tw["lx"], tw["ly"]), crs="EPSG:4326"
    )
    sub["name"] = sub["NAME"].fillna("").map(civil_name)
    hit = gpd.sjoin(lp, sub[sub["name"] != ""][["name", "geometry"]], how="left", predicate="within")
    names = hit.drop_duplicates("i").set_index("i")["name"]
    tw["name"] = [n if isinstance(n, str) else "" for n in names.reindex(range(len(tw)))]
    print(f"  civil names for {(tw['name'] != '').sum()} of {len(tw)} townships")

    sec = sec.rename(columns={"PLSSID": "plssid"})
    sec["n"] = [
        section_number(v) if t == "SN" else None
        for v, t in zip(sec["FRSTDIVNO"], sec["FRSTDIVTYP"], strict=True)
    ]
    sec = sec[["plssid", "n", "geometry"]]

    tw[["plssid", "label", "name", "lx", "ly", "geometry"]].to_parquet(tw_pq)
    sec.to_parquet(sec_pq)
    print(f"wrote {tw_pq.name} ({len(tw)}), {sec_pq.name} ({len(sec)})")


def county_of(points: gpd.GeoDataFrame, counties: gpd.GeoDataFrame) -> list[str]:
    """County FIPS of each point ('' when none), so the map can show only a focused county's labels."""
    j = gpd.sjoin(points, counties[["fips", "geometry"]], how="left", predicate="within")
    s = j[~j.index.duplicated(keep="first")]["fips"].reindex(points.index)
    return [f if isinstance(f, str) else "" for f in s]


def build_tiles(out, tiles) -> None:
    require_tippecanoe()
    counties_pq = out / "counties.parquet"
    if not counties_pq.exists():
        sys.exit(f"{counties_pq.name} missing: run scripts/prepare_boundaries.py first")
    co = gpd.read_parquet(counties_pq)
    co = co[co["state_fips"].isin(FIELD_STATES)]
    tw = gpd.read_parquet(out / "plss_townships.parquet")
    sec = gpd.read_parquet(out / "plss_sections.parquet")

    tmp = out / "_tmp_plss"
    tmp.mkdir(exist_ok=True)
    names = ("townships", "township_labels", "sections", "section_labels")
    paths = {name: tmp / f"{name}.geojsonl" for name in names}

    def feature(props: dict, geom: dict, minzoom: int) -> str:
        return json.dumps({"type": "Feature", "properties": props, "tippecanoe": {"minzoom": minzoom},
                           "geometry": geom}) + "\n"

    tw_pts = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(tw["lx"], tw["ly"]), crs="EPSG:4326", index=tw.index
    )
    tw_county = county_of(tw_pts, co)
    with paths["townships"].open("w") as f, paths["township_labels"].open("w") as fl:
        for r, cf in zip(tw.itertuples(), tw_county, strict=True):
            w, s, e, n = (round(v, 5) for v in r.geometry.bounds)
            props = {"plssid": r.plssid, "label": township_label(r.label), "name": r.name}
            bbox = {"w": w, "s": s, "e": e, "n": n}
            f.write(feature({**props, **bbox}, r.geometry.__geo_interface__, TOWNSHIP_MIN_ZOOM))
            fl.write(feature({**props, "county_fips": cf}, {"type": "Point", "coordinates": [r.lx, r.ly]},
                             TOWNSHIP_MIN_ZOOM))

    numbered = sec[sec["n"].notna()]
    sec_xy = [label_point(g, 0.0002) for g in numbered.geometry]
    sec_pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy([p[0] for p in sec_xy], [p[1] for p in sec_xy]),
                               crs="EPSG:4326", index=numbered.index)
    sec_county = county_of(sec_pts, co)
    with paths["sections"].open("w") as f:
        for g in sec.geometry:
            f.write(feature({}, g.__geo_interface__, SECTION_MIN_ZOOM))
    with paths["section_labels"].open("w") as f:
        for n, xy, cf in zip(numbered["n"], sec_xy, sec_county, strict=True):
            f.write(feature({"n": int(n), "county_fips": cf}, {"type": "Point", "coordinates": list(xy)},
                            SECTION_MIN_ZOOM))

    layers: list[str] = []
    for name, path in paths.items():
        layers += ["-L", f"{name}:{path}"]
    # Write next to the target, then swap it in: the API mmaps plss.pmtiles (see prepare_boundaries.py).
    building = tiles.with_suffix(".building.pmtiles")
    run_tippecanoe([
        "-o", str(building),
        f"-Z{TOWNSHIP_MIN_ZOOM}", f"-z{MAX_ZOOM}",
        "--name", "Field Shift survey townships and sections",
        "--attribution", "BLM National PLSS CadNSDI; US Census Bureau TIGERweb",
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
    print(f"wrote {tiles.name} ({tiles.stat().st_size / 1e6:.1f} MB; restart the API to serve it)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--tiles-only", action="store_true", help="only rebuild plss.pmtiles from the cached parquet"
    )
    args = ap.parse_args()
    out = data_dir()
    tiles = out / "plss.pmtiles"
    if not args.tiles_only:
        download(out, args.force)
    if args.force or args.tiles_only or not tiles.exists():
        build_tiles(out, tiles)
    else:
        print(f"{tiles.name} exists, skipping (use --force to rebuild)")


if __name__ == "__main__":
    main()
