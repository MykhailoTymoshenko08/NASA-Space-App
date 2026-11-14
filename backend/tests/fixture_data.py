"""Tiny synthetic DATA_DIR so tests never need `make data` or network.

Layout: one state ("Iowa", 19) made of two square counties around Des Moines:
  19153 "Polk"  lon -93.80..-93.40, lat 41.50..41.85   (pilot)
  19169 "Story" lon -93.80..-93.40, lat 41.85..42.20   (not pilot)
Fields (all in Polk): F1 is a ~600 m square centred on (41.60, -93.60); F2 sits ~1 km east.
"""

import gzip
import json
from pathlib import Path

import geopandas as gpd
import shapely
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import write as pmtiles_write

from app.geo.tiles import tile_bbox

POLK = shapely.box(-93.80, 41.50, -93.40, 41.85)
STORY = shapely.box(-93.80, 41.85, -93.40, 42.20)
IOWA = shapely.box(-93.80, 41.50, -93.40, 42.20)

# ~0.0072 deg lon x 0.0054 deg lat ~ 600 m x 600 m at this latitude.
F1 = shapely.box(-93.6036, 41.5973, -93.5964, 41.6027)
F2 = shapely.box(-93.5856, 41.5973, -93.5784, 41.6027)
F1_POINT = (41.60, -93.60)  # (lat, lon) inside F1

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


def build(d: Path, with_fields: bool = True) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    states = [{"fips": "19", "name": "Iowa", "postal": "IA", "bbox": _bbox(IOWA)}]
    counties = [
        {
            "fips": fips, "name": name, "state_fips": "19", "state_postal": "IA",
            "bbox": _bbox(g),
            "centroid": {"lat": g.centroid.y, "lon": g.centroid.x},
            "has_field_coverage": fips == "19153",
        }
        for fips, name, g in (("19153", "Polk", POLK), ("19169", "Story", STORY))
    ]
    (d / "states.json").write_text(json.dumps(states))
    (d / "counties.json").write_text(json.dumps(counties))
    gpd.GeoDataFrame(
        {"fips": ["19"], "name": ["Iowa"], "postal": ["IA"]}, geometry=[IOWA], crs=4326
    ).to_parquet(d / "states.parquet")
    gpd.GeoDataFrame(
        {
            "fips": ["19153", "19169"], "name": ["Polk", "Story"],
            "state_fips": ["19", "19"], "state_postal": ["IA", "IA"],
        },
        geometry=[POLK, STORY], crs=4326,
    ).to_parquet(d / "counties.parquet")
    _write_pmtiles(d / "boundaries.pmtiles", range(0, 11), IOWA.bounds)

    if with_fields:
        gpd.GeoDataFrame(
            {
                "field_id": ["fld_f1aaaaaaaa", "fld_f2bbbbbbbb"],
                "crop_class": ["Corn", ""],
                "area_ha": [36.0, 36.0],
                "county_fips": ["19153", "19153"],
                "crop_history": [
                    json.dumps([{"year": 2024, "crop": "Corn"}, {"year": 2023, "crop": "Soybeans"}]),
                    "[]",
                ],
                "csb_id": ["1", "2"],
            },
            geometry=[F1, F2], crs=4326,
        ).to_parquet(d / "fields.parquet")
        (d / "fields_meta.json").write_text(json.dumps({
            "field_data_version": "test-1",
            "field_boundary_source": {
                "name": "USDA Crop Sequence Boundaries", "edition": "2024",
                "estimated_csb": True, "attribution": "test", "url": None,
            },
        }))
        _write_pmtiles(d / "fields.pmtiles", range(11, 17), F1.union(F2).bounds)
    return d


def tile_for(lat: float, lon: float, z: int) -> tuple[int, int, int]:
    import math

    n = 1 << z
    x = int((lon + 180) / 360 * n)
    r = math.radians(lat)
    y = int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n)
    assert tile_bbox(z, x, y)[0] <= lon <= tile_bbox(z, x, y)[2]
    return z, x, y
