"""Look up the soil rating of every CSB field in some counties ahead of time, for /v1/comparisons/area.

The API fills missing ratings in the background when an area is first ranked; this script does the same
work up front (for a demo, or a whole state overnight) so rankings are complete on the first request.

Source: USDA NRCS SSURGO through Soil Data Access, one point inside each field (ST_PointOnSurface):
NCCPI v3.0 (0-100), dominant soil name and drainage class. Stored in `field_soil` in DATABASE_URL.
About 6 s per 400 fields: a county (2,000 to 21,000 fields) takes 1 to 5 minutes, a whole state
about 2.5 hours.

  uv run python scripts/prepare_field_soil.py --county 19153 --county 19169
  uv run python scripts/prepare_field_soil.py --state IA          # every county of a field state
  --force looks up fields that already have a row again.

Idempotent: by default only fields without a row are looked up. Batches that fail are retried three times,
then skipped (run the script again later).
"""

import argparse
import asyncio
import sys
import time

import httpx
from _common import get_settings

from app.comparisons.area import AreaStore
from app.comparisons.soil_batch import BATCH_SIZE, fetch_point_soils
from app.core.config import FIELD_STATES

POSTAL_TO_FIPS = {postal: fips for fips, postal in FIELD_STATES.items()}


def log(msg: str) -> None:
    print(msg, flush=True)


def counties_of(store: AreaStore, state_fips: str) -> list[str]:
    with store._pool.connection() as c:
        rows = c.execute(
            "SELECT DISTINCT county_fips FROM fields WHERE left(county_fips, 2) = %s ORDER BY 1",
            (state_fips,),
        ).fetchall()
    return [r["county_fips"].strip() for r in rows]


async def fill_county(store: AreaStore, client: httpx.AsyncClient, fips: str, force: bool) -> tuple[int, int]:
    rows = store.fields_in("f.county_fips = %(county)s", {"county": fips}, 10**7)
    todo = [(r.field_id, r.lon, r.lat) for r in rows if force or not r.rated]
    done = failed = 0
    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i:i + BATCH_SIZE]
        for attempt in range(3):
            try:
                store.save_soils(await fetch_point_soils(client, batch))
                done += len(batch)
                break
            except Exception as e:  # noqa: BLE001 - retried, then skipped
                log(f"  {fips}: batch {i // BATCH_SIZE + 1} failed ({e!r}), attempt {attempt + 1}/3")
                await asyncio.sleep(5 * (attempt + 1))
        else:
            failed += len(batch)
    return done, failed


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--county", action="append", default=[], help="5-digit county FIPS (repeatable)")
    ap.add_argument("--state", action="append", default=[], choices=sorted(POSTAL_TO_FIPS),
                    help="every county of a field state (repeatable)")
    ap.add_argument("--force", action="store_true", help="look up fields that already have a rating")
    args = ap.parse_args()
    if not args.county and not args.state:
        ap.error("give --county and/or --state")

    store = AreaStore.connect(get_settings().database_url)
    if store is None:
        log("No `fields` table in DATABASE_URL: run `make data-csb` first.")
        return 1
    counties = list(dict.fromkeys(
        [*args.county, *(c for s in args.state for c in counties_of(store, POSTAL_TO_FIPS[s]))]))
    t0 = time.time()
    total_failed = 0
    async with httpx.AsyncClient(headers={"User-Agent": "FieldShift/0.1 (soil prefill)"}) as client:
        for n, fips in enumerate(counties, 1):
            t = time.time()
            done, failed = await fill_county(store, client, fips, args.force)
            total_failed += failed
            took = time.time() - t
            log(f"[{n}/{len(counties)}] {fips}: {done:,} looked up, {failed:,} failed ({took:.0f} s)")
    store.close()
    log(f"done in {time.time() - t0:.0f} s" + (f"; {total_failed:,} fields failed, run again" if total_failed
                                                  else ""))
    return 1 if total_failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
