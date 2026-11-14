"""CSB field polygons in PostGIS: point lookups, id lookups and crop history.

Tables are created and filled by scripts/prepare_csb.py (`make data-csb`):
  fields(field_id PK, edition, src_id, crop_class, area_ha, county_fips, geom MultiPolygon/4326) + GiST
  field_crop_history(field_id, year, crop, PK(field_id, year))
  field_data_meta(id = 1, meta jsonb): edition, counts, tile zooms written by the import and tile build.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import shapely
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

log = logging.getLogger(__name__)

# `{s}` is a table-name suffix: the import builds `fields_new` etc. and swaps them in atomically.
SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE fields{s} (
    field_id    text PRIMARY KEY,
    edition     text NOT NULL,
    src_id      text NOT NULL,
    crop_class  text,
    area_ha     double precision NOT NULL,
    county_fips char(5),
    geom        geometry(MultiPolygon, 4326) NOT NULL
);
CREATE TABLE field_crop_history{s} (
    field_id text NOT NULL,
    year     smallint NOT NULL,
    crop     text NOT NULL,
    PRIMARY KEY (field_id, year)
);
"""
INDEX_SQL = "CREATE INDEX fields{s}_geom_gist ON fields{s} USING gist (geom);"
META_SQL = (
    "CREATE TABLE IF NOT EXISTS field_data_meta (id int PRIMARY KEY CHECK (id = 1), meta jsonb NOT NULL);"
)

_COLS = "f.field_id, f.crop_class, f.area_ha, f.county_fips, ST_AsBinary(f.geom) AS wkb"
# Candidates from the KNN index (planar degrees), then ranked by true EPSG:5070 distance in metres.
_KNN_CANDIDATES = 8


@dataclass(frozen=True)
class FieldRecord:
    field_id: str
    crop_class: str | None
    area_ha: float
    county_fips: str
    geometry: shapely.MultiPolygon | shapely.Polygon  # EPSG:4326
    crop_history: list[tuple[int, str]] = field(default_factory=list)  # newest first


class FieldStore:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    @classmethod
    def connect(cls, url: str) -> "FieldStore | None":
        """Open a pool and check the tables exist. None (with a log line) when they cannot be used."""
        pool = ConnectionPool(url, min_size=1, max_size=8, open=False, kwargs={"row_factory": dict_row})
        try:
            pool.open(wait=True, timeout=5)
            with pool.connection() as c:
                ok = c.execute("SELECT to_regclass('public.fields') IS NOT NULL AS ok").fetchone()["ok"]
            if not ok:
                log.warning("table `fields` missing (run `make data-csb`): points resolve to buffered points")
                pool.close()
                return None
        except Exception as e:  # noqa: BLE001 - any DB failure means "no field data"
            log.error("PostGIS unavailable at %s (%s): points resolve to buffered points",
                      url.split("@")[-1], e)
            pool.close()
            return None
        return cls(pool)

    def close(self) -> None:
        self._pool.close()

    def meta(self) -> dict[str, Any]:
        with self._pool.connection() as c:
            if c.execute("SELECT to_regclass('public.field_data_meta') IS NULL AS no").fetchone()["no"]:
                return {}
            row = c.execute("SELECT meta FROM field_data_meta WHERE id = 1").fetchone()
        if not row:
            return {}
        m = row["meta"]
        return json.loads(m) if isinstance(m, str) else m

    def _history(self, c, field_id: str) -> list[tuple[int, str]]:
        rows = c.execute(
            "SELECT year, crop FROM field_crop_history WHERE field_id = %s ORDER BY year DESC", (field_id,)
        ).fetchall()
        return [(int(r["year"]), r["crop"]) for r in rows]

    def _record(self, c, row: dict) -> FieldRecord:
        return FieldRecord(
            field_id=row["field_id"],
            crop_class=row["crop_class"] or None,
            area_ha=float(row["area_ha"]),
            county_fips=(row["county_fips"] or "").strip(),
            geometry=shapely.from_wkb(bytes(row["wkb"])),
            crop_history=self._history(c, row["field_id"]),
        )

    def get(self, field_id: str) -> FieldRecord | None:
        with self._pool.connection() as c:
            row = c.execute(f"SELECT {_COLS} FROM fields f WHERE f.field_id = %s", (field_id,)).fetchone()
            return self._record(c, row) if row else None

    def containing(self, lon: float, lat: float) -> FieldRecord | None:
        """Polygon containing the point. Smallest wins if polygons overlap."""
        with self._pool.connection() as c:
            row = c.execute(
                f"""SELECT {_COLS} FROM fields f
                    WHERE ST_Contains(f.geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                    ORDER BY ST_Area(f.geom) LIMIT 1""",
                (lon, lat),
            ).fetchone()
            return self._record(c, row) if row else None

    def nearest(self, lon: float, lat: float, max_distance_m: float) -> tuple[FieldRecord, float] | None:
        """Nearest polygon within `max_distance_m` (EPSG:5070 metres), with its distance."""
        if max_distance_m <= 0:
            return None
        with self._pool.connection() as c:
            row = c.execute(
                f"""WITH p AS (SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS g),
                    cand AS (
                        SELECT f.* FROM fields f, p ORDER BY f.geom <-> p.g LIMIT {_KNN_CANDIDATES}
                    )
                    SELECT {_COLS},
                           ST_Distance(ST_Transform(f.geom, 5070), ST_Transform(p.g, 5070)) AS dist
                    FROM cand f, p
                    ORDER BY dist LIMIT 1""",
                (lon, lat),
            ).fetchone()
            if not row or row["dist"] > max_distance_m:
                return None
            return self._record(c, row), float(row["dist"])
