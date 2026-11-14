"""Concurrent point context with bounded, in-memory caching of successful source results."""

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from app.core.cache import MemoryCache
from app.core.errors import ApiException, ErrorCode
from app.field_info import sources
from app.models import FieldInfo, LatLon, Quality

log = logging.getLogger(__name__)

# Rough state envelopes, WGS84 (west, south, east, north). These intentionally need
# neither prepared GIS data nor PostGIS. Small border false positives are acceptable.
STATE_BOUNDS = {
    "IA": (-96.640, 40.375, -90.140, 43.502),
    "IL": (-91.514, 36.970, -87.495, 42.509),
    "NE": (-104.054, 39.999, -95.308, 43.001),
}


def validate_coverage(point: LatLon) -> None:
    if not any(w <= point.lon <= e and s <= point.lat <= n for w, s, e, n in STATE_BOUNDS.values()):
        raise ApiException(ErrorCode.OUTSIDE_COVERAGE,
                           "Field information is available only in Iowa, Illinois and Nebraska.",
                           {"supported_states": ["IA", "IL", "NE"]})


class FieldInfoService:
    def __init__(self, client: httpx.AsyncClient, timeout_s: float = 4.0):
        self.client = client
        self.timeout_s = timeout_s
        self.cache = MemoryCache(maxsize=1024, ttl_s=24 * 3600)

    async def info(self, point: LatLon) -> FieldInfo:
        # Validate the exact request before cache lookup, including on warm-cache requests.
        validate_coverage(point)
        point = LatLon(lat=round(point.lat, 4), lon=round(point.lon, 4))
        upstreams = (
            (sources.fetch_power_recent, sources.RECENT_SPECS),
            (sources.fetch_power_normal, sources.NORMAL_SPECS),
            (sources.fetch_soil, sources.SOIL_SPECS),
            (sources.fetch_terrain, sources.TERRAIN_SPECS),
            (sources.fetch_land_cover, [sources.LAND_SPEC]),
        )

        async def run(fetch, specs):
            key = f"{fetch.__name__}:{point.lat:.4f},{point.lon:.4f}"
            if (hit := self.cache.get(key)) is not None:
                return hit, True
            try:
                metrics = await asyncio.wait_for(fetch(self.client, point), self.timeout_s)
                if all(m.quality != Quality.unavailable for m in metrics):
                    self.cache.set(key, metrics, 24 * 3600)
                return metrics, False
            except (TimeoutError, httpx.TimeoutException):
                reason = "The data service did not answer in time. Try again shortly."
            except Exception:
                log.warning("Field info source %s failed", fetch.__name__, exc_info=True)
                reason = "The data service is unavailable right now. Try again shortly."
            return [spec.unavailable(reason) for spec in specs], False

        results = await asyncio.gather(*(run(fetch, specs) for fetch, specs in upstreams))
        return FieldInfo(point=point, generated_at=datetime.now(UTC),
                         cached=all(hit for _, hit in results),
                         metrics=[metric for metrics, _ in results for metric in metrics])
