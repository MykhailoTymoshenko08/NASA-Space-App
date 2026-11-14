"""USGS 3DEP elevation via the Elevation Point Query Service (EPQS).

Docs: https://epqs.nationalmap.gov/v1/docs
Checked live 2026-11-14: GET /v1/json?x=<lon>&y=<lat>&wkid=4326&units=Meters returns
{"value": "263.56", "resolution": 1, ...}. It is often slow (6-13 s), so the snapshot service lets it
finish in the background and serves the cached value on the next request.
"""

import math

import httpx

from app.data_sources.base import MetricSpec, get_with_retry
from app.models import FieldSelection, Metric, MetricCategory, MetricSource, Quality

URL = "https://epqs.nationalmap.gov/v1/json"
SRC = MetricSource(
    dataset="USGS 3D Elevation Program (3DEP), Elevation Point Query Service",
    provider="USGS",
    url="https://www.usgs.gov/3d-elevation-program",
)
SPEC = MetricSpec("elevation_m", "Elevation", MetricCategory.terrain, "m", Quality.measured, SRC,
                  10.0, "Ground elevation at the anchor point of the selection.")
NODATA = -1_000_000  # EPQS reports large negative values outside coverage


async def sample(client: httpx.AsyncClient, lon: float, lat: float) -> tuple[float | None, float | None]:
    response = await get_with_retry(client, URL, params={
        "x": lon, "y": lat, "wkid": 4326, "units": "Meters", "includeDate": "false",
    })
    payload = response.json()
    try:
        value = float(payload.get("value"))
    except (TypeError, ValueError):
        return None, None
    if not math.isfinite(value) or value <= NODATA:
        return None, None
    try:
        resolution = float(payload.get("resolution"))
    except (TypeError, ValueError):
        resolution = None
    if resolution is not None and (not math.isfinite(resolution) or resolution <= 0):
        resolution = None
    return value, resolution


class ElevationSource:
    name = "usgs_3dep"
    specs = [SPEC]
    # Answer the snapshot quickly; the fetch keeps running in the background and is cached.
    soft_timeout_s = 1.5

    async def fetch(self, client: httpx.AsyncClient, selection: FieldSelection) -> list[Metric]:
        anchor = selection.anchor
        v, resolution = await sample(client, anchor.lon, anchor.lat)
        if v is None:
            return [SPEC.unavailable("No 3DEP elevation at this point.")]
        return [SPEC.metric(round(v, 1), resolution_m=resolution or SPEC.resolution_m)]
