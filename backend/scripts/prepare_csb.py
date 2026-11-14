"""USDA Crop Sequence Boundaries (CSB) for Iowa, Illinois, Nebraska: PostGIS import and PMTiles build.

Source: USDA NASS CSB 2018-2025 (rev23), national FileGDB in a zip (3.76 GB), public domain:
  https://www.nass.usda.gov/Research_and_Science/Crop-Sequence-Boundaries/
Checked 2026-11-14: layer `national1825`, 15,973,095 MultiPolygons, CRS = NAD83 Albers with the
EPSG:5070 parameters, columns CSBID (15 chars, unique within the edition), CDL2018..CDL2025 (CDL crop
code per year), STATEFIPS, CNTYFIPS (3 digits), ... The server answers only HTTP Range requests (a
plain GET returns 500), so the download is done in ranged chunks and is resumable.

Steps:
  import   download (once) -> stream the 3 states (STATEFIPS 17, 19, 31) with pyogrio into an UNLOGGED
           staging table -> ST_MakeValid, drop empties, area_ha in EPSG:5070, transform to EPSG:4326 ->
           `fields_new` + `field_crop_history_new` -> GiST index -> swap with the live tables in one
           transaction. Re-running is safe; it skips when the same source is already imported (--force
           re-imports).
  tiles    export from PostGIS to GeoJSONSeq -> tippecanoe -> data/csb_ia_il_ne.pmtiles, layer `fields`
           (field_id, crop_class, area_ha). Tries min zoom 11, 12, 13 (max 14) and keeps the lowest one
           that builds within tippecanoe's tile size limit WITHOUT dropping any polygon, then checks that
           every field_id is present at that min zoom. Zooms and stats go to field_data_meta.tiles.

Crop names: scripts/cdl_codes.json (official CDL categorization codes). Codes 0 (background) and
81 (clouds/no data) mean "no crop that year" and are left out of the history.

Usage: uv run python scripts/prepare_csb.py import|tiles [--force]
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
import pyarrow as pa
from _common import USER_AGENT, data_dir, require_tippecanoe

from app.core.config import FIELD_STATES, get_settings
from app.geo.field_store import INDEX_SQL, META_SQL, SCHEMA_SQL

CSB_URL = (
    "https://www.nass.usda.gov/sites/default/files/Research_and_Science/Crop-Sequence-Boundaries/"
    "datasets/NationalCSB_2018-2025_rev23.zip"
)
ZIP_NAME = "NationalCSB_2018-2025_rev23.zip"
GDB = "CSB1825.gdb"
LAYER = "national1825"
YEARS = list(range(2018, 2026))
EDITION = "2018-2025"
ID_PREFIX = f"csb{YEARS[-1]}_"
FIELD_DATA_VERSION = f"csb{EDITION}-rev23-ia-il-ne"
SRC_SRID = 5070
TILES_NAME = "csb_ia_il_ne.pmtiles"
MAX_ZOOM = 14
MIN_ZOOM_CANDIDATES = (11, 12, 13)
CHUNK = 256 * 1024 * 1024
CDL_CODES = Path(__file__).with_name("cdl_codes.json")


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------- download ----------
def download(dest: Path) -> None:
    """Resumable ranged download (the NASS server rejects plain GETs of this file)."""
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=300, follow_redirects=True) as c:
        size = int(c.head(CSB_URL).raise_for_status().headers["content-length"])
        if dest.exists() and dest.stat().st_size == size:
            return
        if size > 15e9:
            sys.exit(f"CSB download is {size / 1e9:.1f} GB (> 15 GB stop limit)")
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(".part")
        have = part.stat().st_size if part.exists() else 0
        with part.open("ab") as f:
            while have < size:
                end = min(have + CHUNK, size) - 1
                for attempt in range(6):
                    try:
                        r = c.get(CSB_URL, headers={"Range": f"bytes={have}-{end}"})
                        r.raise_for_status()
                        if r.status_code != 206 or len(r.content) != end - have + 1:
                            raise httpx.HTTPError(f"short or non-ranged response {r.status_code}")
                        break
                    except httpx.HTTPError as e:
                        if attempt == 5:
                            raise
                        log(f"retry after {e!r}")
                        time.sleep(5 * (attempt + 1))
                f.write(r.content)
                have += len(r.content)
                log(f"downloaded {have / 1e9:.2f} / {size / 1e9:.2f} GB")
        part.replace(dest)


# ---------- import ----------
STAGE_SQL = """
DROP TABLE IF EXISTS fields_stage;
CREATE UNLOGGED TABLE fields_stage (
    src_id text NOT NULL, county_fips text NOT NULL, cdl smallint[] NOT NULL, wkb bytea NOT NULL
);
"""


def _meta(conn) -> dict:
    conn.execute(META_SQL)
    row = conn.execute("SELECT meta FROM field_data_meta WHERE id = 1").fetchone()
    return row[0] if row else {}


def _save_meta(conn, meta: dict) -> None:
    conn.execute(
        "INSERT INTO field_data_meta VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET meta = EXCLUDED.meta",
        (json.dumps(meta),),
    )


def stage(conn, zip_path: Path) -> int:
    import pyogrio.raw

    src = f"/vsizip/{zip_path}/{GDB}"
    states = ",".join(f"'{f}'" for f in FIELD_STATES)
    cols = ["CSBID", "STATEFIPS", "CNTYFIPS", *(f"CDL{y}" for y in YEARS)]
    conn.execute(STAGE_SQL)
    n = 0
    with pyogrio.raw.open_arrow(
        src, layer=LAYER, columns=cols, where=f"STATEFIPS IN ({states})", batch_size=50_000,
        use_pyarrow=True,
    ) as (meta, reader):
        geom_col = meta["geometry_name"] or "wkb_geometry"
        with conn.cursor().copy("COPY fields_stage (src_id, county_fips, cdl, wkb) FROM STDIN") as cp:
            for batch in reader:
                t = pa.Table.from_batches([batch])
                ids = t["CSBID"].to_pylist()
                st = t["STATEFIPS"].to_pylist()
                co = t["CNTYFIPS"].to_pylist()
                cdl = list(zip(*(t[f"CDL{y}"].to_pylist() for y in YEARS), strict=True))
                wkb = t[geom_col].to_pylist()
                for i in range(len(ids)):
                    cp.write_row((ids[i], st[i] + co[i], [c or 0 for c in cdl[i]], wkb[i]))
                n += len(ids)
                log(f"staged {n:,} polygons")
    return n


def build_tables(conn, staged: int) -> dict:
    codes = json.loads(CDL_CODES.read_text())
    no_crop = set(codes["no_crop_codes"])
    conn.execute("DROP TABLE IF EXISTS fields_new, field_crop_history_new, cdl_codes")
    conn.execute(SCHEMA_SQL.format(s="_new"))
    conn.execute("CREATE TEMP TABLE cdl_codes (code smallint PRIMARY KEY, name text NOT NULL)")
    with conn.cursor().copy("COPY cdl_codes FROM STDIN") as cp:
        for k, v in codes["codes"].items():
            if int(k) not in no_crop:
                cp.write_row((int(k), v))

    log("building fields_new (MakeValid, area in EPSG:5070, transform to 4326) ...")
    conn.execute(
        f"""
        INSERT INTO fields_new (field_id, edition, src_id, crop_class, area_ha, county_fips, geom)
        SELECT %(prefix)s || t.src_id, %(edition)s, t.src_id, c.name,
               ST_Area(t.g) / 10000.0, t.county_fips, ST_Multi(ST_Transform(t.g, 4326))
        FROM (
            SELECT s.src_id, s.county_fips, s.cdl,
                   ST_CollectionExtract(ST_MakeValid(
                       CASE WHEN ST_HasArc(g0) THEN ST_CurveToLine(g0) ELSE g0 END), 3) AS g
            FROM (SELECT *, ST_GeomFromWKB(wkb, {SRC_SRID}) AS g0 FROM fields_stage) s
        ) t
        LEFT JOIN cdl_codes c ON c.code = t.cdl[{len(YEARS)}]
        WHERE NOT ST_IsEmpty(t.g)
        """,
        {"prefix": ID_PREFIX, "edition": EDITION},
    )
    inserted = conn.execute("SELECT count(*) FROM fields_new").fetchone()[0]
    log(f"{inserted:,} fields ({staged - inserted:,} dropped: empty after ST_MakeValid)")

    log("building field_crop_history_new ...")
    conn.execute(
        """
        INSERT INTO field_crop_history_new (field_id, year, crop)
        SELECT f.field_id, y.year, c.name
        FROM fields_stage s
        JOIN fields_new f ON f.field_id = %(prefix)s || s.src_id
        CROSS JOIN LATERAL unnest(s.cdl, %(years)s::smallint[]) AS y(code, year)
        JOIN cdl_codes c ON c.code = y.code
        """,
        {"prefix": ID_PREFIX, "years": YEARS},
    )
    hist = conn.execute("SELECT count(*) FROM field_crop_history_new").fetchone()[0]
    log(f"{hist:,} history rows; indexing ...")
    conn.execute(INDEX_SQL.format(s="_new"))
    per_state = dict(conn.execute(
        "SELECT left(county_fips, 2), count(*) FROM fields_new GROUP BY 1 ORDER BY 1").fetchall())
    no_crop_latest = conn.execute("SELECT count(*) FROM fields_new WHERE crop_class IS NULL").fetchone()[0]
    return {
        "staged": staged, "fields": inserted, "dropped_empty": staged - inserted,
        "history_rows": hist, "fields_without_latest_crop": no_crop_latest,
        "per_state": {FIELD_STATES[k]: v for k, v in per_state.items()},
    }


def swap(conn) -> None:
    conn.execute("DROP TABLE IF EXISTS fields, field_crop_history")
    conn.execute("ALTER TABLE fields_new RENAME TO fields")
    conn.execute("ALTER TABLE field_crop_history_new RENAME TO field_crop_history")
    conn.execute("ALTER INDEX fields_new_pkey RENAME TO fields_pkey")
    conn.execute("ALTER INDEX field_crop_history_new_pkey RENAME TO field_crop_history_pkey")
    conn.execute("ALTER INDEX fields_new_geom_gist RENAME TO fields_geom_gist")
    conn.execute("DROP TABLE IF EXISTS fields_stage")


def cmd_import(force: bool) -> None:
    url = get_settings().database_url
    zip_path = data_dir() / "raw" / "csb" / ZIP_NAME
    with psycopg.connect(url, autocommit=True) as conn:
        meta = _meta(conn)
        if not force and meta.get("field_data_version") == FIELD_DATA_VERSION and meta.get("counts"):
            n = meta["counts"]["fields"]
            log(f"{FIELD_DATA_VERSION} already imported ({n:,} fields); --force redoes it")
            return
    t0 = time.time()
    download(zip_path)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SET maintenance_work_mem = '1GB'")
        staged = stage(conn, zip_path)
        counts = build_tables(conn, staged)
        with conn.transaction():
            swap(conn)
            _save_meta(conn, {
                "field_data_version": FIELD_DATA_VERSION, "edition": EDITION, "source": CSB_URL,
                "years": YEARS, "counts": counts, "imported_at": datetime.now(UTC).isoformat(),
            })
        conn.execute("ANALYZE fields")
        conn.execute("ANALYZE field_crop_history")
    log(f"import done in {time.time() - t0:.0f} s: {json.dumps(counts)}")


# ---------- tiles ----------
def export_geojsonseq(conn, path: Path) -> int:
    n = 0
    # A named (server-side) cursor streams rows; it needs a transaction even in autocommit mode.
    with path.open("w") as f, conn.transaction(), conn.cursor(name="export") as cur:
        cur.itersize = 20_000
        cur.execute("SELECT field_id, coalesce(crop_class, ''), round(area_ha::numeric, 2)::float8, "
                    "ST_AsGeoJSON(geom, 6) FROM fields")
        for fid, crop, area, geom in cur:
            props = json.dumps({"field_id": fid, "crop_class": crop, "area_ha": area})
            f.write(f'{{"type":"Feature","properties":{props},"geometry":{geom}}}\n')
            n += 1
    return n


def tippecanoe(src: Path, out: Path, min_zoom: int) -> tuple[bool, str]:
    cmd = [
        require_tippecanoe(), "--force", "--quiet", "-P",
        "-o", str(out), "-l", "fields", f"-Z{min_zoom}", f"-z{MAX_ZOOM}",
        "-y", "field_id", "-y", "crop_class", "-y", "area_ha",
        "--name", "Field Shift CSB fields (IA, IL, NE)",
        "--attribution", "USDA NASS Crop Sequence Boundaries",
        # Never drop or merge polygons: no dot-dropping, no tiny-polygon reduction, no feature-count
        # cap. The default 500 KB tile size limit stays, so a too-dense min zoom fails the build
        # instead of silently losing fields.
        "-r1", "--no-tiny-polygon-reduction", "--no-feature-limit",
        "--detect-shared-borders",
        str(src),
    ]
    log("+ " + " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode == 0, (p.stderr or "")[-2000:]


ID_RE = re.compile(r'"field_id": ?"([^"]+)"')


def ids_at_zoom(path: Path, z: int) -> set[str]:
    """Distinct field_ids present in all tiles of zoom `z` (decoded with tippecanoe-decode)."""
    seen: set[str] = set()
    p = subprocess.Popen(["tippecanoe-decode", "-z", str(z), "-Z", str(z), str(path)],
                         stdout=subprocess.PIPE, text=True)
    assert p.stdout
    for line in p.stdout:
        seen.update(ID_RE.findall(line))
    p.wait()
    return seen


def cmd_tiles(force: bool) -> None:
    url = get_settings().database_url
    out = data_dir() / TILES_NAME
    with psycopg.connect(url, autocommit=True) as conn:
        meta = _meta(conn)
        if not meta.get("counts"):
            sys.exit("no imported fields: run `prepare_csb.py import` first")
        tiles = meta.get("tiles", {})
        if (not force and out.exists() and tiles.get("field_data_version") == meta["field_data_version"]
                and tiles.get("size_bytes") == out.stat().st_size):
            log(f"{out.name} is current (z{tiles['min_zoom']}-{tiles['max_zoom']}); --force rebuilds it")
            return
        t0 = time.time()
        src = data_dir() / "_csb_fields.geojsonl"
        n = export_geojsonseq(conn, src)
        log(f"exported {n:,} features in {time.time() - t0:.0f} s")
        tmp = out.with_suffix(".building.pmtiles")
        attempts = []
        try:
            for z in MIN_ZOOM_CANDIDATES:
                t1 = time.time()
                ok, err = tippecanoe(src, tmp, z)
                attempts.append({"min_zoom": z, "ok": ok, "seconds": round(time.time() - t1)})
                if ok:
                    break
                log(f"min zoom {z} failed (tile size limit?): {err.strip().splitlines()[-1:]}")
            else:
                sys.exit(f"tippecanoe failed at every min zoom {MIN_ZOOM_CANDIDATES}")
        finally:
            src.unlink(missing_ok=True)
        min_zoom = attempts[-1]["min_zoom"]
        build_s = round(time.time() - t0)
        log(f"built z{min_zoom}-{MAX_ZOOM} in {build_s} s; checking every field is in z{min_zoom} ...")
        present = ids_at_zoom(tmp, min_zoom)
        if len(present) != n:
            sys.exit(f"{n - len(present):,} of {n:,} fields missing at z{min_zoom}: not publishing")
        tmp.replace(out)
        meta["tiles"] = {
            "file": out.name, "min_zoom": min_zoom, "max_zoom": MAX_ZOOM, "features": n,
            "size_bytes": out.stat().st_size, "build_seconds": build_s, "attempts": attempts,
            "field_data_version": meta["field_data_version"], "built_at": datetime.now(UTC).isoformat(),
        }
        _save_meta(conn, meta)
    log(f"wrote {out} ({out.stat().st_size / 1e9:.2f} GB): {json.dumps(meta['tiles'])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["import", "tiles"])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    {"import": cmd_import, "tiles": cmd_tiles}[args.step](args.force)


if __name__ == "__main__":
    main()
