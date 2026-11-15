"""Rank every CSB field in a county, a box or a township outline: size, crop history and soil.

The fields of one area (at most AREA_MAX_FIELDS) are read in one query with their crop history and the
stored soil rating, then filtered, ranked and given percentiles in Python. Ranking is by soil productivity
(NCCPI), size or distance; percentiles say where each field stands among the matching fields of the area.

Soil ratings live in `field_soil` (same database as `fields`), one row per field once looked up, also when
the survey has no rating (so it is not asked again). Missing ratings are filled in the background from Soil
Data Access, one batch at a time for the whole process; the response says `filling` meanwhile and the
client asks again. `scripts/prepare_field_soil.py` fills whole counties ahead of time.
"""

import asyncio
import bisect
import logging
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
import shapely
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pyproj import Geod
from shapely.geometry import shape
from starlette.concurrency import run_in_threadpool

from app.comparisons.history import summarize_history
from app.comparisons.soil_batch import BATCH_SIZE, fetch_point_soils
from app.core.config import FIELD_STATES
from app.core.errors import ApiException, ErrorCode, not_found
from app.models import (
    AreaBBoxRef,
    AreaCountyRef,
    AreaInfo,
    AreaRanking,
    AreaRankingRequest,
    AreaSoilStatus,
    AreaSort,
    AreaStats,
    LatLon,
    Quartiles,
    RankedField,
)

log = logging.getLogger(__name__)

MAX_SPAN_DEG = 1.0  # a box or outline at most about 1 x 1 degree (a large county)
MAX_POSITIONS = 2000
RETRY_AFTER_FAILURE_S = 120.0
CACHE_TTL_S = 300.0
CACHE_MAX_AREAS = 16
SOIL_METHOD = (
    "SSURGO soil at one point inside each field (NCCPI v3.0, 0-100). A screening value: the side-by-side "
    "comparison reads soil over the whole field."
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS field_soil (
    field_id   text PRIMARY KEY,
    mukey      text,
    nccpi      real,
    soil_name  text,
    drainage   text,
    fetched_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fields_county_fips_idx ON fields (county_fips);
"""

_SELECT = """
SELECT f.field_id, f.area_ha, f.county_fips,
       ST_X(p.pt) AS lon, ST_Y(p.pt) AS lat,
       ST_XMin(f.geom) AS w, ST_YMin(f.geom) AS s, ST_XMax(f.geom) AS e, ST_YMax(f.geom) AS n,
       s.field_id IS NOT NULL AS rated, s.nccpi, s.soil_name, s.drainage,
       h.years, h.crops
FROM fields f
CROSS JOIN LATERAL (SELECT ST_PointOnSurface(f.geom) AS pt) p
LEFT JOIN field_soil s ON s.field_id = f.field_id
LEFT JOIN LATERAL (
    SELECT array_agg(year ORDER BY year DESC) AS years, array_agg(crop ORDER BY year DESC) AS crops
    FROM field_crop_history WHERE field_id = f.field_id
) h ON true
WHERE {where}
LIMIT %(cap)s
"""


@dataclass
class FieldRow:
    field_id: str
    area_ha: float
    county_fips: str
    lon: float
    lat: float
    bbox: list[float]
    rated: bool
    nccpi: float | None
    soil_name: str | None
    drainage: str | None
    history: list[tuple[int, str]]


class AreaStore:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    @classmethod
    def connect(cls, url: str) -> "AreaStore | None":
        pool = ConnectionPool(url, min_size=1, max_size=4, open=False, kwargs={"row_factory": dict_row})
        try:
            pool.open(wait=True, timeout=5)
            with pool.connection() as c:
                if not c.execute("SELECT to_regclass('public.fields') IS NOT NULL AS ok").fetchone()["ok"]:
                    pool.close()
                    return None
                c.execute(SCHEMA_SQL)
        except Exception as e:  # noqa: BLE001 - area ranking is optional
            log.error("area ranking unavailable (%s)", e)
            pool.close()
            return None
        return cls(pool)

    def close(self) -> None:
        self._pool.close()

    def fields_in(self, where: str, params: dict, cap: int) -> list[FieldRow]:
        with self._pool.connection() as c, c.transaction():
            # JIT compilation costs more than the whole query here (about 0.3 s of 0.5 s for 5,000 fields).
            c.execute("SET LOCAL jit = off")
            rows = c.execute(_SELECT.format(where=where), {**params, "cap": cap}).fetchall()
        return [FieldRow(
            field_id=r["field_id"], area_ha=float(r["area_ha"]), county_fips=(r["county_fips"] or "").strip(),
            lon=float(r["lon"]), lat=float(r["lat"]),
            bbox=[round(float(r[k]), 6) for k in ("w", "s", "e", "n")],
            rated=bool(r["rated"]), nccpi=float(r["nccpi"]) if r["nccpi"] is not None else None,
            soil_name=r["soil_name"], drainage=r["drainage"],
            history=list(zip(r["years"] or [], r["crops"] or [], strict=True)),
        ) for r in rows]

    def save_soils(self, soils: dict[str, dict]) -> None:
        if not soils:
            return
        with self._pool.connection() as c, c.cursor() as cur:
            cur.executemany(
                """INSERT INTO field_soil (field_id, mukey, nccpi, soil_name, drainage)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (field_id) DO UPDATE SET mukey = EXCLUDED.mukey, nccpi = EXCLUDED.nccpi,
                       soil_name = EXCLUDED.soil_name, drainage = EXCLUDED.drainage, fetched_at = now()""",
                [(fid, s["mukey"], s["nccpi"], s["soil_name"], s["drainage"]) for fid, s in soils.items()],
            )


SoilFetch = Callable[[httpx.AsyncClient, list[tuple[str, float, float]]], Awaitable[dict[str, dict]]]


class SoilFiller:
    """Background soil lookups per area. One SDA batch at a time for the whole process."""

    def __init__(self, store: AreaStore, client: httpx.AsyncClient, fetch: SoilFetch = fetch_point_soils):
        self.store = store
        self.client = client
        self.fetch = fetch
        self._tasks: dict[str, asyncio.Task] = {}
        self._failed_at: dict[str, float] = {}
        self._gate = asyncio.Semaphore(1)

    def filling(self, key: str) -> bool:
        task = self._tasks.get(key)
        return task is not None and not task.done()

    def start(self, key: str, points: list[tuple[str, float, float]]) -> bool:
        """Start filling `points` for area `key` unless already running or it failed a moment ago."""
        if not points or self.filling(key):
            return self.filling(key)
        if time.monotonic() - self._failed_at.get(key, -1e9) < RETRY_AFTER_FAILURE_S:
            return False
        task = asyncio.create_task(self._run(key, points))
        self._tasks[key] = task
        task.add_done_callback(lambda t, key=key: self._forget(key, t))
        return True

    def _forget(self, key: str, task: asyncio.Task) -> None:
        if self._tasks.get(key) is task:
            del self._tasks[key]

    async def _run(self, key: str, points: list[tuple[str, float, float]]) -> None:
        try:
            for i in range(0, len(points), BATCH_SIZE):
                async with self._gate:
                    soils = await self.fetch(self.client, points[i:i + BATCH_SIZE])
                await run_in_threadpool(self.store.save_soils, soils)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - reported as `partial`; retried after a pause
            log.warning("soil fill for %s failed", key, exc_info=True)
            self._failed_at[key] = time.monotonic()

    async def aclose(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# ---------- ranking ----------

def _quartiles(values: list[float]) -> Quartiles | None:
    if not values:
        return None
    if len(values) == 1:
        v = round(values[0], 1)
        return Quartiles(p25=v, median=v, p75=v)
    q1, q2, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return Quartiles(p25=round(q1, 1), median=round(q2, 1), p75=round(q3, 1))


def _percentiles(values: dict[str, float]) -> dict[str, int]:
    """Share of the other fields with a lower value, 0-100. Empty for fewer than two fields."""
    ordered = sorted(values.values())
    n = len(ordered)
    if n < 2:
        return {}
    return {fid: round(100 * bisect.bisect_left(ordered, v) / (n - 1)) for fid, v in values.items()}


def _area_where(svc, area) -> tuple[str, dict, AreaInfo, str]:
    """SQL condition, its parameters, the echo of the area, and a key for background soil work."""
    if isinstance(area, AreaCountyRef):
        fips = area.county_fips
        county = svc.boundaries.county(fips)
        if county is None:
            raise not_found(f"Unknown county {fips}.", county_fips=fips)
        if fips[:2] not in FIELD_STATES:
            raise ApiException(ErrorCode.OUTSIDE_COVERAGE,
                               "Field rankings cover Iowa, Illinois and Nebraska.",
                               {"supported_states": sorted(FIELD_STATES.values())})
        info = AreaInfo(kind="county", county=svc.boundaries.ref(county), bbox=county.bbox)
        return "f.county_fips = %(county)s", {"county": fips}, info, f"county:{fips}"
    if isinstance(area, AreaBBoxRef):
        w, s, e, n = area.bbox
        if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
            raise ApiException(ErrorCode.VALIDATION_ERROR, "bbox must be [west, south, east, north].")
        geom = shapely.box(w, s, e, n)
        kind = "bbox"
    else:
        coords = area.polygon.coordinates
        if sum(len(r) for r in coords) > MAX_POSITIONS or any(len(r) < 4 or r[0] != r[-1] for r in coords):
            raise ApiException(
                ErrorCode.VALIDATION_ERROR,
                f"polygon rings must be closed, with at most {MAX_POSITIONS} positions in all.")
        try:
            geom = shape(area.polygon.model_dump())
        except Exception:  # noqa: BLE001
            raise ApiException(ErrorCode.VALIDATION_ERROR, "polygon is not valid GeoJSON.") from None
        if not geom.is_valid or geom.is_empty:
            raise ApiException(ErrorCode.VALIDATION_ERROR, "polygon is self-intersecting or empty.")
        kind = "polygon"
    w, s, e, n = geom.bounds
    if e - w > MAX_SPAN_DEG or n - s > MAX_SPAN_DEG:
        raise ApiException(ErrorCode.VALIDATION_ERROR,
                           f"The area is too large: keep it within {MAX_SPAN_DEG:g} degree on each side, "
                           "or rank a county instead.", {"max_span_deg": MAX_SPAN_DEG})
    where = ("f.geom && ST_GeomFromText(%(wkt)s, 4326) "
             "AND ST_Intersects(ST_GeomFromText(%(wkt)s, 4326), p.pt)")
    wkt = shapely.to_wkt(geom, rounding_precision=6)
    info = AreaInfo(kind=kind, county=None, bbox=[round(v, 6) for v in (w, s, e, n)])
    return where, {"wkt": wkt}, info, f"{kind}:{wkt}"


def _matches(row: FieldRow, req: AreaRankingRequest, history) -> bool:
    f = req.filters
    if f.min_area_ha is not None and row.area_ha < f.min_area_ha:
        return False
    if f.max_area_ha is not None and row.area_ha > f.max_area_ha:
        return False
    if f.min_productivity is not None and (row.nccpi is None or row.nccpi < f.min_productivity):
        return False
    if f.latest_crops:
        wanted = {c.strip().lower() for c in f.latest_crops}
        if (history.latest_crop or "").strip().lower() not in wanted:
            return False
    if f.exclude_continuous_corn and history.corn_in_a_row >= 3:
        return False
    return True


def rank_rows(
    rows: list[FieldRow], req: AreaRankingRequest,
) -> tuple[list[RankedField], list[RankedField], int, AreaStats]:
    """(page items, pinned items, number of matching fields, stats over the matching fields)."""
    histories = {r.field_id: summarize_history(r.history, "usda_csb" if r.history else "none") for r in rows}
    matching = [r for r in rows if _matches(r, req, histories[r.field_id])]
    distances: dict[str, float] = {}
    if req.near is not None and rows:
        geod = Geod(ellps="WGS84")
        _, _, metres = geod.inv([req.near.lon] * len(rows), [req.near.lat] * len(rows),
                                [r.lon for r in rows], [r.lat for r in rows])
        distances = {r.field_id: round(m / 1000, 2) for r, m in zip(rows, metres, strict=True)}

    if req.sort == AreaSort.productivity:
        key = lambda r: (r.nccpi is None, -(r.nccpi or 0), -r.area_ha, r.field_id)  # noqa: E731
    elif req.sort == AreaSort.area:
        key = lambda r: (-r.area_ha, r.field_id)  # noqa: E731
    else:
        key = lambda r: (distances[r.field_id], r.field_id)  # noqa: E731
    ordered = sorted(matching, key=key)
    rank = {r.field_id: i + 1 for i, r in enumerate(ordered)}
    area_pct = _percentiles({r.field_id: r.area_ha for r in matching})
    prod_pct = _percentiles({r.field_id: r.nccpi for r in matching if r.nccpi is not None})

    def out(r: FieldRow) -> RankedField:
        return RankedField(
            field_id=r.field_id, rank=rank.get(r.field_id), matches_filters=r.field_id in rank,
            anchor=LatLon(lat=round(r.lat, 6), lon=round(r.lon, 6)), bbox=r.bbox, county_fips=r.county_fips,
            area_ha=round(r.area_ha, 2), history=histories[r.field_id],
            productivity=round(r.nccpi, 1) if r.nccpi is not None else None,
            soil_name=r.soil_name, drainage=r.drainage, distance_km=distances.get(r.field_id),
            area_percentile=area_pct.get(r.field_id), productivity_percentile=prod_pct.get(r.field_id),
        )

    page = [out(r) for r in ordered[req.offset:req.offset + req.limit]]
    by_id = {r.field_id: r for r in rows}
    pinned = [out(by_id[fid]) for fid in dict.fromkeys(req.pinned_field_ids) if fid in by_id]
    stats = AreaStats(
        area_ha=_quartiles([r.area_ha for r in matching]),
        productivity=_quartiles([r.nccpi for r in matching if r.nccpi is not None]),
    )
    return page, pinned, len(matching), stats


class AreaRankingService:
    def __init__(self, store: AreaStore, filler: SoilFiller | None, max_fields: int):
        self.store = store
        self.filler = filler
        self.max_fields = max_fields
        # Areas whose fields all have a soil rating do not change: keep them briefly so paging is cheap.
        self._cache: dict[str, tuple[float, list[FieldRow]]] = {}

    async def _rows(self, key: str, where: str, params: dict) -> list[FieldRow]:
        hit = self._cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
        rows = await run_in_threadpool(self.store.fields_in, where, params, self.max_fields + 1)
        if rows and all(r.rated for r in rows):
            if len(self._cache) >= CACHE_MAX_AREAS:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (time.monotonic(), rows)
        return rows

    async def rank(self, svc, req: AreaRankingRequest) -> AreaRanking:
        where, params, info, key = _area_where(svc, req.area)
        rows = await self._rows(key, where, params)
        if len(rows) > self.max_fields:
            raise ApiException(ErrorCode.VALIDATION_ERROR,
                               f"This area has more than {self.max_fields:,} fields. Pick a smaller area.",
                               {"max_fields": self.max_fields})
        page, pinned, total, stats = rank_rows(rows, req)

        unrated = [(r.field_id, r.lon, r.lat) for r in rows if not r.rated]
        filling = self.filler.start(key, unrated) if self.filler is not None and unrated else False
        rated = len(rows) - len(unrated)
        if not unrated:
            status = "complete"
        elif filling:
            status = "filling"
        else:
            status = "partial" if rated else "unavailable"

        notes = [
            "Field areas are USDA crop sequence boundaries: an algorithmic estimate, not ownership lines.",
            "Percentiles compare each field with the matching fields of this area: 80 means larger "
            "(or better soil) than 80% of them.",
        ]
        if status in ("filling", "partial", "unavailable"):
            more = " Ask again in a few seconds for more." if filling else ""
            notes.append(f"Soil ratings exist for {rated:,} of {len(rows):,} fields. Fields without one "
                         f"rank last when sorting by productivity.{more}")
        found = {p.field_id for p in pinned}
        missing_pins = [fid for fid in dict.fromkeys(req.pinned_field_ids) if fid not in found]
        if missing_pins:
            notes.append(f"Not in this area: {', '.join(missing_pins)}.")
        end = req.offset + len(page)
        return AreaRanking(
            area=info, total=total, sort=req.sort, offset=req.offset, limit=req.limit,
            next_offset=end if end < total else None,
            soil=AreaSoilStatus(status=status, fields_rated=rated, fields_total=len(rows),
                                method=SOIL_METHOD),
            stats=stats, items=page, pinned=pinned, notes=notes,
        )

    async def aclose(self) -> None:
        if self.filler is not None:
            await self.filler.aclose()
        self.store.close()

