"""Common shape for upstream data source clients."""

import asyncio
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.models import FieldSelection, Metric, MetricCategory, MetricSource, Quality


async def get_with_retry(client: httpx.AsyncClient, url: str, *, params: dict) -> httpx.Response:
    """Give slow point services two bounded attempts; callers enforce the total background deadline."""
    for attempt in range(2):
        try:
            response = await client.get(url, params=params, timeout=httpx.Timeout(25.0, connect=5.0))
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as error:
            if attempt or error.response.status_code not in (502, 503, 504):
                raise
        except httpx.TransportError:
            if attempt:
                raise
        await asyncio.sleep(0.25)
    raise AssertionError("unreachable")


@dataclass(frozen=True)
class MetricSpec:
    """Static description of one metric a source produces."""

    key: str
    label: str
    category: MetricCategory
    unit: str
    quality: Quality
    source: MetricSource
    resolution_m: float | None
    note: str | None = None

    def metric(self, value, **kw) -> Metric:
        fields = dict(
            key=self.key, label=self.label, category=self.category, unit=self.unit,
            quality=self.quality, source=self.source, resolution_m=self.resolution_m, note=self.note,
        )
        fields.update(kw)
        if value is None:
            return self.unavailable(kw.get("unavailable_reason") or "No value for this location.")
        return Metric(value=value, **fields)

    def unavailable(self, reason: str) -> Metric:
        return Metric(
            key=self.key, label=self.label, category=self.category, unit=self.unit,
            value=None, quality=Quality.unavailable, unavailable_reason=reason,
            source=self.source, resolution_m=self.resolution_m, note=self.note,
            as_of=None, period=None,
        )


class DataSource(Protocol):
    name: str
    specs: list[MetricSpec]

    async def fetch(self, client: httpx.AsyncClient, selection: FieldSelection) -> list[Metric]:
        """Return one Metric per spec (unavailable ones included). May raise on transport errors.
        Point datasets sample `selection.anchor`; area datasets may use `selection.geometry`."""
        ...


def all_unavailable(src: DataSource, reason: str) -> list[Metric]:
    return [s.unavailable(reason) for s in src.specs]
