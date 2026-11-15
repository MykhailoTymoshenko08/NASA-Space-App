"""Copy the CSB field data into a small hosted Postgres (e.g. Neon's 1 GB free tier) in a compact layout.

The local import (`make data-csb`) needs about 3.2 GB: one geometry per field plus one row per field and year
of crop history. This script writes the same data in about 0.6 GB:

  field_shapes(field_id PK, crop_class, area_ha, county_fips, g bytea, crops smallint[])
    g      the polygon as TWKB with 5 decimals (about 1 m), about 7x smaller than the geometry
    crops  one crop code per year (field_crop_codes), first element = first year of field_data_meta
  field_crop_codes(code PK, name)

and adds views with the original names and columns, so the API reads it unchanged:

  fields             (field_id, crop_class, area_ha, county_fips, geom)  geom decoded from g on the fly
  field_crop_history (field_id, year, crop)

The GiST index is on the same expression the `fields` view uses for `geom`, so ST_Contains, && and the
<-> KNN on the view use it. Area stays exact (`area_ha` is copied); point lookups can differ by about 1 m
at a field edge. Data is streamed with COPY from the source DB, nothing is written to the source.

  uv run python scripts/publish_slim_fields.py --target "postgresql://...?sslmode=require"
  --source defaults to DATABASE_URL; --force replaces field data already in the target.
"""

import argparse
import json
import sys
import time

import psycopg
from _common import get_settings

PRECISION = 5  # TWKB decimals: 1e-5 degree is about 1.1 m
GEOM_EXPR = "ST_SetSRID(ST_GeomFromTWKB(g), 4326)"

TARGET_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE field_crop_codes (code smallint PRIMARY KEY, name text NOT NULL UNIQUE);
CREATE TABLE field_shapes (
    field_id    text NOT NULL,
    crop_class  text,
    area_ha     double precision NOT NULL,
    county_fips char(5),
    g           bytea NOT NULL,
    crops       smallint[]
);
CREATE TABLE IF NOT EXISTS field_data_meta (id int PRIMARY KEY CHECK (id = 1), meta jsonb NOT NULL);
"""

TARGET_FINISH = """
ALTER TABLE field_shapes ADD PRIMARY KEY (field_id);
CREATE INDEX field_shapes_geom_gist ON field_shapes USING gist (({geom}));
-- Same name as the index the API creates on a plain `fields` table (app/comparisons/area.py).
CREATE INDEX fields_county_fips_idx ON field_shapes (county_fips);
CREATE VIEW fields AS
    SELECT field_id, crop_class, area_ha, county_fips, {geom} AS geom FROM field_shapes;
CREATE VIEW field_crop_history AS
    SELECT s.field_id, ({first_year} + u.i - 1)::smallint AS year, c.name AS crop
    FROM field_shapes s
    CROSS JOIN LATERAL unnest(s.crops) WITH ORDINALITY AS u(code, i)
    JOIN field_crop_codes c ON c.code = u.code;
"""

DROP_TARGET = """
DROP VIEW IF EXISTS field_crop_history, fields;
DROP TABLE IF EXISTS field_crop_history, fields, field_shapes, field_crop_codes CASCADE;
"""


def _size(c, rel: str) -> str:
    return c.execute(f"SELECT pg_size_pretty(pg_total_relation_size('{rel}'))").fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="connection URL of the hosted database")
    ap.add_argument("--source", default=None, help="local DB with the full import (default: DATABASE_URL)")
    ap.add_argument("--force", action="store_true", help="replace field data already in the target")
    args = ap.parse_args()
    source = args.source or get_settings().database_url

    with psycopg.connect(source) as src, psycopg.connect(args.target, autocommit=True) as tgt:
        meta = src.execute("SELECT meta FROM field_data_meta WHERE id = 1").fetchone()
        if not meta:
            sys.exit("source has no field_data_meta: run `make data-csb` first")
        meta = meta[0]
        years = sorted(meta.get("years") or [r[0] for r in src.execute(
            "SELECT DISTINCT year FROM field_crop_history ORDER BY 1")])
        first_year, last_year = years[0], years[-1]
        crops = [r[0] for r in src.execute("SELECT DISTINCT crop FROM field_crop_history ORDER BY 1")]
        print(f"{len(crops)} crops, years {first_year}-{last_year}")

        exists = tgt.execute("SELECT to_regclass('public.field_shapes') IS NOT NULL "
                             "OR to_regclass('public.fields') IS NOT NULL").fetchone()[0]
        if exists and not args.force:
            sys.exit("target already has field data: pass --force to replace it")
        tgt.execute(DROP_TARGET)
        tgt.execute(TARGET_SCHEMA)
        with tgt.cursor().copy("COPY field_crop_codes (code, name) FROM STDIN") as cp:
            for code, name in enumerate(crops, start=1):
                cp.write_row((code, name))

        # Codes on the source side through a temporary table (the source itself is not changed).
        src.execute("CREATE TEMP TABLE _codes (code smallint, name text)")
        with src.cursor().copy("COPY _codes FROM STDIN") as cp:
            for code, name in enumerate(crops, start=1):
                cp.write_row((code, name))
        query = f"""
            SELECT f.field_id, f.crop_class, f.area_ha, f.county_fips, ST_AsTWKB(f.geom, {PRECISION}),
                   ARRAY(SELECT k.code FROM generate_series({first_year}, {last_year}) y
                         LEFT JOIN field_crop_history h ON h.field_id = f.field_id AND h.year = y
                         LEFT JOIN _codes k ON k.name = h.crop ORDER BY y)::smallint[]
            FROM fields f"""
        t0, rows, nbytes = time.time(), 0, 0
        with src.cursor().copy(f"COPY ({query}) TO STDOUT (FORMAT binary)") as cin, \
                tgt.cursor().copy("COPY field_shapes FROM STDIN (FORMAT binary)") as cout:
            for chunk in cin:
                cout.write(chunk)
                nbytes += len(chunk)
                if nbytes // (50 << 20) != (nbytes - len(chunk)) // (50 << 20):
                    print(f"  {nbytes >> 20} MB sent, {time.time() - t0:.0f} s", flush=True)
        rows = tgt.execute("SELECT count(*) FROM field_shapes").fetchone()[0]
        print(f"{rows} fields copied in {time.time() - t0:.0f} s; building indexes and views")

        tgt.execute(TARGET_FINISH.format(geom=GEOM_EXPR, first_year=int(first_year)))
        meta = {**meta, "layout": {"kind": "slim", "twkb_precision": PRECISION}}
        tgt.execute("INSERT INTO field_data_meta (id, meta) VALUES (1, %s) "
                    "ON CONFLICT (id) DO UPDATE SET meta = EXCLUDED.meta", (json.dumps(meta),))
        tgt.execute("ANALYZE field_shapes; ANALYZE field_crop_codes")
        db_size = tgt.execute("SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
        print(f"field_shapes {_size(tgt, 'field_shapes')}, database {db_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
