"""Tiny synthetic DATA_DIR + PostGIS rows, so tests never need `make data` or network.

Layout: Iowa (19) made of two square counties around Des Moines, plus a Texas (48) county for points
outside the supported states:
  19153 "Polk"   lon -93.80..-93.40, lat 41.50..41.85
  19169 "Story"  lon -93.80..-93.40, lat 41.85..42.20
  48453 "Travis" lon -98.00..-97.50, lat 30.00..30.50
CSB polygons (both in Polk): F1 is a ~600 m square centred on (41.60, -93.60) with crop history; F2 sits
~1 km east with no mapped crops. Loaded into a scratch PostGIS database by `load_fields`.
"""

import gzip
import json
from pathlib import Path

import geopandas as gpd
import shapely
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import write as pmtiles_write

from app.geo.field_store import INDEX_SQL, META_SQL, SCHEMA_SQL

POLK = shapely.box(-93.80, 41.50, -93.40, 41.85)
STORY = shapely.box(-93.80, 41.85, -93.40, 42.20)
IOWA = shapely.box(-93.80, 41.50, -93.40, 42.20)
TRAVIS = shapely.box(-98.00, 30.00, -97.50, 30.50)
TEXAS = TRAVIS
TEXAS_POINT = (30.27, -97.74)  # (lat, lon) Austin

# ~0.0072 deg lon x 0.0054 deg lat ~ 600 m x 600 m at this latitude.
F1 = shapely.box(-93.6036, 41.5973, -93.5964, 41.6027)
F2 = shapely.box(-93.5856, 41.5973, -93.5784, 41.6027)
F1_POINT = (41.60, -93.60)  # (lat, lon) inside F1
F1_ID = "csb2025_190000000001"
F2_ID = "csb2025_190000000002"
F1_HISTORY = [(2025, "Corn"), (2024, "Soybeans"), (2023, "Corn")]  # newest first
FIELD_META = {
    "field_data_version": "test-1",
    "edition": "2018-2025",
    "tiles": {"min_zoom": 12, "max_zoom": 14},
}

FAKE_TILE = gzip.compress(b"\x1a\x00fake-mvt")


def _bbox(g) -> list[float]:
    return [round(v, 5) for v in g.bounds]


def _write_pmtiles(path: Path, zooms: range, bbox) -> None:
    w_, s_, e_, n_ = bbox
    entries = []
    import math

    for z in zooms:
        n = 1 << z
        x0 = int((w_ + 180) / 360 * n)
        x1 = int((e_ + 180) / 360 * n)

        def ty(lat, n=n):
            r = math.radians(lat)
            return int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n)

        for x in range(x0, x1 + 1):
            for y in range(ty(n_), ty(s_) + 1):
                entries.append(zxy_to_tileid(z, x, y))
    with pmtiles_write(str(path)) as w:
        for tid in sorted(entries):
            w.write_tile(tid, FAKE_TILE)
        w.finalize(
            {
                "tile_type": TileType.MVT,
                "tile_compression": Compression.GZIP,
                "min_zoom": zooms.start,
                "max_zoom": zooms.stop - 1,
                "min_lon_e7": int(w_ * 1e7),
                "min_lat_e7": int(s_ * 1e7),
                "max_lon_e7": int(e_ * 1e7),
                "max_lat_e7": int(n_ * 1e7),
                "center_zoom": zooms.start,
                "center_lon_e7": int((w_ + e_) / 2 * 1e7),
                "center_lat_e7": int((s_ + n_) / 2 * 1e7),
            },
            {"vector_layers": []},
        )


def build(d: Path) -> Path:
    """Boundary files only. Field polygons live in PostGIS (`load_fields`)."""
    d.mkdir(parents=True, exist_ok=True)
    states = [
        {"fips": "19", "name": "Iowa", "postal": "IA", "bbox": _bbox(IOWA)},
        {"fips": "48", "name": "Texas", "postal": "TX", "bbox": _bbox(TEXAS)},
    ]
    county_rows = (
        ("19153", "Polk", "19", "IA", POLK),
        ("19169", "Story", "19", "IA", STORY),
        ("48453", "Travis", "48", "TX", TRAVIS),
    )
    counties = [
        {
            "fips": fips, "name": name, "state_fips": st, "state_postal": postal,
            "bbox": _bbox(g),
            "centroid": {"lat": g.centroid.y, "lon": g.centroid.x},
            "has_field_coverage": False,
        }
        for fips, name, st, postal, g in county_rows
    ]
    (d / "states.json").write_text(json.dumps(states))
    (d / "counties.json").write_text(json.dumps(counties))
    gpd.GeoDataFrame(
        {"fips": ["19", "48"], "name": ["Iowa", "Texas"], "postal": ["IA", "TX"]},
        geometry=[IOWA, TEXAS], crs=4326,
    ).to_parquet(d / "states.parquet")
    gpd.GeoDataFrame(
        {
            "fips": [r[0] for r in county_rows], "name": [r[1] for r in county_rows],
            "state_fips": [r[2] for r in county_rows], "state_postal": [r[3] for r in county_rows],
        },
        geometry=[r[4] for r in county_rows], crs=4326,
    ).to_parquet(d / "counties.parquet")
    _write_pmtiles(d / "boundaries.pmtiles", range(0, 11), IOWA.bounds)
    # Stand-in for csb_ia_il_ne.pmtiles (served whole by /v1/tiles/fields.pmtiles).
    _write_pmtiles(d / "csb_ia_il_ne.pmtiles", range(12, 15), F1.union(F2).bounds)
    return d


def load_fields(conn) -> None:
    """Create the field tables (same DDL as scripts/prepare_csb.py) and insert F1, F2."""
    conn.execute(SCHEMA_SQL.format(s=""))
    conn.execute(INDEX_SQL.format(s=""))
    conn.execute(META_SQL)
    for fid, geom, crop in ((F1_ID, F1, "Corn"), (F2_ID, F2, None)):
        conn.execute(
            """INSERT INTO fields VALUES (%s, '2018-2025', %s, %s,
                   ST_Area(ST_Transform(ST_GeomFromText(%s, 4326), 5070)) / 10000, '19153',
                   ST_Multi(ST_GeomFromText(%s, 4326)))""",
            (fid, fid.split("_", 1)[1], crop, geom.wkt, geom.wkt),
        )
    for year, crop in F1_HISTORY:
        conn.execute("INSERT INTO field_crop_history VALUES (%s, %s, %s)", (F1_ID, year, crop))
    conn.execute("INSERT INTO field_data_meta VALUES (1, %s)", (json.dumps(FIELD_META),))


def tile_for(lat: float, lon: float, z: int) -> tuple[int, int, int]:
    import math

    n = 1 << z
    x = int((lon + 180) / 360 * n)
    r = math.radians(lat)
    y = int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n)
    return z, x, y
