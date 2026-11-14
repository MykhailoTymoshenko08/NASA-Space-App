"""Common shape for upstream data source clients."""

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.models import LatLon, Metric, MetricCategory, MetricSource, Quality


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

    async def fetch(self, client: httpx.AsyncClient, anchor: LatLon) -> list[Metric]:
        """Return one Metric per spec (unavailable ones included). May raise on transport errors."""
        ...


def all_unavailable(src: DataSource, reason: str) -> list[Metric]:
    return [s.unavailable(reason) for s in src.specs]
