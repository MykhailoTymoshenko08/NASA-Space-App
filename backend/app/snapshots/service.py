"""Assemble a Snapshot: all sources fetched concurrently, each with its own timeout.

- A failed or slow source gives `unavailable` metrics; the request never fails because of it.
- A source that times out keeps running in the background; its result lands in the per-source cache
  so the next request for the same spot gets it (USGS elevation routinely takes 6-13 s).
- The whole snapshot is cached for SNAPSHOT_CACHE_TTL_S only when every source answered.
"""

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from app.core.cache import Cache
from app.data_sources.base import DataSource, all_unavailable
from app.data_sources.elevation import ElevationSource
from app.data_sources.power import PowerSource
from app.data_sources.soilgrids import SoilGridsSource
from app.data_sources.ssurgo import SsurgoSource
from app.models import FieldSelection, LatLon, Metric, Quality, Snapshot

log = logging.getLogger(__name__)

BACKGROUND_TIMEOUT_S = 30.0
SOURCE_CACHE_TTL_S = 24 * 3600
TIMEOUT_REASON = "The data service did not answer in time. Try again in a minute."
ERROR_REASON = "The data service is unavailable right now."


def default_sources() -> list[DataSource]:
    return [PowerSource(), SsurgoSource(), ElevationSource(), SoilGridsSource()]


def snapshot_key(sel: FieldSelection) -> str:
    if sel.field_id:
        return f"snap:v1:field:{sel.field_id}"
    return f"snap:v1:pt:{sel.anchor.lat:.2f},{sel.anchor.lon:.2f}"


def _source_key(src: DataSource, anchor: LatLon) -> str:
    return f"src:v1:{src.name}:{anchor.lat:.5f},{anchor.lon:.5f}"


class SnapshotService:
    def __init__(
        self,
        cache: Cache,
        client: httpx.AsyncClient,
        sources: list[DataSource] | None = None,
        source_timeout_s: float = 4.0,
        ttl_s: int = 24 * 3600,
    ):
        self.cache = cache
        self.client = client
        self.sources = sources if sources is not None else default_sources()
        self.timeout = source_timeout_s
        self.ttl = ttl_s
        self._inflight: dict[str, asyncio.Task] = {}

    async def _fetch_and_store(self, src: DataSource, anchor: LatLon, key: str) -> list[Metric]:
        metrics = await asyncio.wait_for(src.fetch(self.client, anchor), BACKGROUND_TIMEOUT_S)
        self.cache.set(key, [m.model_dump(mode="json") for m in metrics], SOURCE_CACHE_TTL_S)
        return metrics

    async def _run(self, src: DataSource, anchor: LatLon) -> tuple[list[Metric], bool]:
        """Return (metrics, complete). complete=False means some metrics are unavailable for a
        transient reason (timeout/error) and must not be cached for long."""
        key = _source_key(src, anchor)
        hit = self.cache.get(key)
        if hit is not None:
            return [Metric(**m) for m in hit], True

        task = self._inflight.get(key)
        if task is None or task.done():
            task = asyncio.create_task(self._fetch_and_store(src, anchor, key))
            self._inflight[key] = task
            task.add_done_callback(lambda t, k=key: self._done(k, t))
        try:
            # shield: a timeout here must not cancel the background fetch.
            timeout = min(self.timeout, getattr(src, "soft_timeout_s", self.timeout))
            return await asyncio.wait_for(asyncio.shield(task), timeout), True
        except TimeoutError:
            log.info("source %s slow; continuing in background", src.name)
            return all_unavailable(src, TIMEOUT_REASON), False
        except Exception as e:  # noqa: BLE001 - any upstream failure becomes unavailable metrics
            log.warning("source %s failed: %r", src.name, e)
            return all_unavailable(src, ERROR_REASON), False

    def _done(self, key: str, task: asyncio.Task) -> None:
        if self._inflight.get(key) is task:
            del self._inflight[key]
        if not task.cancelled() and task.exception() is not None:
            log.debug("background fetch %s failed: %r", key, task.exception())

    async def metrics_for(self, anchor: LatLon) -> tuple[list[Metric], bool]:
        results = await asyncio.gather(*(self._run(s, anchor) for s in self.sources))
        metrics = [m for ms, _ in results for m in ms]
        return metrics, all(ok for _, ok in results)

    async def snapshot(self, selection: FieldSelection) -> Snapshot:
        key = snapshot_key(selection)
        hit = self.cache.get(key)
        if hit is not None:
            return Snapshot(
                selection=selection,
                generated_at=datetime.fromisoformat(hit["generated_at"]),
                cached=True,
                metrics=[Metric(**m) for m in hit["metrics"]],
            )
        metrics, complete = await self.metrics_for(selection.anchor)
        now = datetime.now(UTC).replace(microsecond=0)
        if complete:
            self.cache.set(
                key,
                {"generated_at": now.isoformat(),
                 "metrics": [m.model_dump(mode="json") for m in metrics]},
                self.ttl,
            )
        return Snapshot(selection=selection, generated_at=now, cached=False, metrics=metrics)


def available_count(metrics: list[Metric]) -> int:
    return sum(1 for m in metrics if m.quality != Quality.unavailable)
