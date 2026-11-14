"""Download BLM PLSS sections and townships and build the selectable-unit data + tiles.

Source: BLM National PLSS CadNSDI MapServer (public domain, provided "as is"):
  https://gis.blm.gov/arcgis/rest/services/Cadastral/BLM_Natl_PLSS_CadNSDI/MapServer
  layer 1 = "PLSS Township", layer 2 = "PLSS Section" (First Division), checked 2026-11-14.
  maxRecordCount 2000, so we page with resultOffset (ordered by OBJECTID) and request GeoJSON in
  EPSG:4326. Raw pages are cached in data/raw/plss/<STATE>/ so re-runs never re-download.

Which first-division types we keep (FRSTDIVTYP):
  SN Section and FS Fractional Section: real, surveyed sections -> kept, `division_type` records which.
  Dropped: protracted/unsurveyed (UP, PB, UN, QT), lots (LT), tracts (TR), meandered water (MW),
  other/unknown (OT, UK, AR, UA) and rows with no type. They are not survey sections a farmer
  would recognise; points there fall back to a 500 m buffered point.

Outputs (DATA_DIR):
  sections.parquet   field_id, township_id, section_id, section_number, division_type, label,
                     area_ha, county_fips, geometry (Polygon, EPSG:4326)
  townships.parquet  township_id, label, state, geometry
  plss_meta.json     edition (download date), states, counts, regions (bbox per state)
  fields.pmtiles     layer `fields` (field_id, crop_class "", area_ha, label), z11..14
  boundaries.pmtiles is rebuilt so it gains the `townships` layer (z8-10).

Idempotent: cached pages are reused; outputs are rebuilt only with --force or when missing.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime

import geopandas as gpd
import pandas as pd
import shapely
from _common import data_dir, http_client, require_tippecanoe, run_tippecanoe, write_json

from app.core.config import get_settings

SERVICE = "https://gis.blm.gov/arcgis/rest/services/Cadastral/BLM_Natl_PLSS_CadNSDI/MapServer"
TOWNSHIP_LAYER, SECTION_LAYER = 1, 2
PAGE = 2000
PAUSE_S = 0.5  # be polite to the BLM server
KEEP_TYPES = {"SN": "section", "FS": "fractional_section"}
SECTION_FIELDS = "OBJECTID,PLSSID,FRSTDIVID,FRSTDIVTYP,FRSTDIVTXT,FRSTDIVNO,FRSTDIVDUP"
TOWNSHIP_FIELDS = "OBJECTID,PLSSID,STATEABBR,TWNSHPLAB,PRINMER"


def fetch_pages(client, layer: int, where: str, fields: str, cache_dir) -> list[dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    feats, offset = [], 0
    while True:
        page_file = cache_dir / f"{offset:08d}.geojson"
        if page_file.exists():
            page = json.loads(page_file.read_text())
        else:
            for attempt in range(5):
                try:
                    r = client.get(f"{SERVICE}/{layer}/query", params={
                        "where": where, "outFields": fields, "returnGeometry": "true",
                        "outSR": 4326, "geometryPrecision": 6, "orderByFields": "OBJECTID",
                        "resultOffset": offset, "resultRecordCount": PAGE, "f": "geojson",
                    })
                    r.raise_for_status()
                    page = r.json()
                    if "error" in page:
                        raise RuntimeError(page["error"])
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 4:
                        sys.exit(f"BLM request failed at offset {offset}: {e}")
                    time.sleep(2 ** attempt)
            page_file.write_text(json.dumps(page))
            time.sleep(PAUSE_S)
        batch = page.get("features", [])
        feats.extend(batch)
        more = page.get("exceededTransferLimit") or page.get("properties", {}).get(
            "exceededTransferLimit"
        )
        if not batch or not more:
            break
        offset += len(batch)
        print(f"  {cache_dir.parent.name}/{cache_dir.name}: {len(feats)}", end="\r")
    print(f"  {cache_dir.parent.name}/{cache_dir.name}: {len(feats)} features")
    return feats


def to_gdf(feats: list[dict]) -> gpd.GeoDataFrame:
    feats = [f for f in feats if f.get("geometry")]
    rows = [f["properties"] for f in feats]
    geoms = [shapely.geometry.shape(f["geometry"]) for f in feats]
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=4326)


def largest_polygon(g):
    """Contract geometry is a Polygon: keep the largest part of a multi-part shape."""
    g = shapely.make_valid(g)
    if g.geom_type == "Polygon":
        return g
    polys = [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"]
    for p in getattr(g, "geoms", []):
        if p.geom_type == "MultiPolygon":
            polys.extend(p.geoms)
    return max(polys, key=lambda p: p.area) if polys else None


def clean_sections(raw: gpd.GeoDataFrame, townships: gpd.GeoDataFrame, counties) -> gpd.GeoDataFrame:
    stats = raw["FRSTDIVTYP"].fillna("(none)").value_counts().to_dict()
    df = raw[raw["FRSTDIVTYP"].isin(KEEP_TYPES)].copy()
    print(f"  first-division types: {stats}; kept {len(df)} ({', '.join(KEEP_TYPES)})")

    dup = df["FRSTDIVDUP"].fillna("0").astype(str).str.strip()
    suffix = dup.where(~dup.isin({"", "0"}), "")
    df["field_id"] = "plss:" + df["FRSTDIVID"].astype(str) + suffix.map(lambda s: f"-{s}" if s else "")
    n_dup = int(df["field_id"].duplicated().sum())
    if n_dup:
        # Same id on several rows: exact copies or one section split in parts. Merge, never drop area.
        print(f"  merging {n_dup} extra rows that share a field_id")
        df = df.dissolve(by="field_id", aggfunc="first", as_index=False)

    parts_before = int(df.geometry.geom_type.ne("Polygon").sum())
    df["geometry"] = [largest_polygon(g) for g in df.geometry]
    df = df[df.geometry.notna() & ~df.geometry.is_empty]
    if parts_before:
        print(f"  {parts_before} multi-part/invalid geometries reduced to their largest polygon")

    tw_label = dict(zip(townships["township_id"], townships["label"], strict=False))
    df["township_id"] = df["PLSSID"].astype(str)
    df["section_id"] = df["FRSTDIVID"].astype(str)
    df["section_number"] = pd.to_numeric(df["FRSTDIVNO"], errors="coerce").astype("Int64")
    df["division_type"] = df["FRSTDIVTYP"].map(KEEP_TYPES)

    def label(r) -> str:
        kind = "Section" if r.division_type == "section" else "Fractional section"
        num = f" {int(r.section_number)}" if pd.notna(r.section_number) else ""
        tw = tw_label.get(r.township_id)
        return f"{kind}{num}, {tw}" if tw else f"{kind}{num}"

    df["label"] = [label(r) for r in df.itertuples()]
    proj = df.to_crs(5070)
    df["area_ha"] = (proj.geometry.area / 10_000).round(2)

    pts = gpd.GeoDataFrame(geometry=proj.geometry.representative_point(), crs=5070, index=df.index)
    co = counties.to_crs(5070)[["fips", "geometry"]]
    j = gpd.sjoin(pts, co, predicate="within", how="left")
    j = j[~j.index.duplicated()]
    df["county_fips"] = j["fips"].reindex(df.index).fillna("")
    cols = ["field_id", "township_id", "section_id", "section_number", "division_type", "label",
            "area_ha", "county_fips", "geometry"]
    return gpd.GeoDataFrame(df[cols], geometry="geometry", crs=4326).reset_index(drop=True)


def clean_townships(raw: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    df = raw.copy()
    df["geometry"] = [largest_polygon(g) for g in df.geometry]
    df = df[df.geometry.notna()]
    df["township_id"] = df["PLSSID"].astype(str)
    df["label"] = df["TWNSHPLAB"].fillna("").astype(str)
    df["state"] = df["STATEABBR"].fillna("").astype(str)
    df = df[~df["township_id"].duplicated()]
    return gpd.GeoDataFrame(df[["township_id", "label", "state", "geometry"]], geometry="geometry",
                            crs=4326).reset_index(drop=True)


def build_field_tiles(out, sections: gpd.GeoDataFrame) -> None:
    require_tippecanoe()
    s = get_settings()
    src = out / "_sections.geojsonl"
    with src.open("w") as f:
        for r in sections.itertuples():
            props = {"field_id": r.field_id, "crop_class": "", "area_ha": float(r.area_ha),
                     "label": r.label}
            f.write(json.dumps({"type": "Feature", "properties": props,
                                "geometry": shapely.geometry.mapping(r.geometry)}) + "\n")
    try:
        run_tippecanoe([
            "-o", str(out / "fields.pmtiles"),
            "-l", "fields",
            f"-Z{s.field_tiles_min_zoom}", f"-z{s.field_tiles_max_zoom}",
            "--name", "Field Shift PLSS sections",
            "--attribution", "Bureau of Land Management (PLSS CadNSDI)",
            # Every section must be visible and clickable from min_zoom on.
            "--no-feature-limit", "--no-tile-size-limit",
            "--detect-shared-borders",
            str(src),
        ])
    finally:
        src.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rebuild outputs (cached downloads reused)")
    ap.add_argument("--states", help="comma-separated state postal codes (default: PLSS_STATES)")
    args = ap.parse_args()

    out = data_dir()
    if not (out / "counties.parquet").exists():
        sys.exit("counties.parquet missing: run scripts/prepare_boundaries.py first")
    states = [s.strip().upper() for s in (args.states or get_settings().plss_states).split(",")
              if s.strip()]
    sec_pq, tw_pq, meta = out / "sections.parquet", out / "townships.parquet", out / "plss_meta.json"
    t0 = time.time()

    if args.force or not (sec_pq.exists() and tw_pq.exists() and meta.exists()):
        raw_root = out / "raw" / "plss"
        sec_feats, tw_feats = [], []
        with http_client(timeout=180) as c:
            for st in states:
                print(f"{st}:")
                tw_feats += fetch_pages(c, TOWNSHIP_LAYER, f"STATEABBR='{st}'", TOWNSHIP_FIELDS,
                                        raw_root / st / "townships")
                sec_feats += fetch_pages(c, SECTION_LAYER, f"PLSSID LIKE '{st}%'", SECTION_FIELDS,
                                         raw_root / st / "sections")
        if not sec_feats:
            sys.exit(f"No PLSS sections for {states}; PLSS may not exist there.")
        counties = gpd.read_parquet(out / "counties.parquet")
        townships = clean_townships(to_gdf(tw_feats))
        sections = clean_sections(to_gdf(sec_feats), townships, counties)
        sections.to_parquet(sec_pq)
        townships.to_parquet(tw_pq)

        regions = []
        for st in states:
            sub = sections[sections["township_id"].str.startswith(st)]
            if len(sub):
                regions.append({"name": f"{st} (PLSS)", "bbox": [round(v, 4) for v in sub.total_bounds]})
        downloaded = datetime.now(UTC).date().isoformat()
        write_json(meta, {
            "field_data_version": f"plss-{downloaded}-{'-'.join(sorted(states)).lower()}",
            "edition": downloaded,
            "states": states,
            "sections": len(sections),
            "townships": len(townships),
            "division_types": sections["division_type"].value_counts().to_dict(),
            "regions": regions,
            "source_url": SERVICE,
        })
        print(f"wrote {sec_pq.name} ({len(sections)} sections), {tw_pq.name} ({len(townships)} townships)")
        build_tiles = True
    else:
        print("sections/townships exist, skipping (use --force to rebuild)")
        sections = gpd.read_parquet(sec_pq)
        build_tiles = not (out / "fields.pmtiles").exists()

    if build_tiles or args.force:
        build_field_tiles(out, sections)
        # Rebuild boundaries so they carry the `townships` layer.
        from prepare_boundaries import build_tiles as build_boundary_tiles

        build_boundary_tiles(out, out / "boundaries.pmtiles")
    for f in ("sections.parquet", "townships.parquet", "fields.pmtiles", "boundaries.pmtiles"):
        p = out / f
        if p.exists():
            print(f"  {f}: {p.stat().st_size / 1e6:.1f} MB")
    print(f"done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
