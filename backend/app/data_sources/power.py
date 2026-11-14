"""NASA POWER daily point API: humidity, temperature, precipitation, modeled soil wetness.

Docs: https://power.larc.nasa.gov/docs/services/api/temporal/daily/
Parameters (community AG): https://power.larc.nasa.gov/docs/services/api/system/manager/parameters/
Checked live 2026-11-14 (API v2.10.3): RH2M (%), T2M (C), PRECTOTCORR (mm/day), GWETTOP and
GWETROOT (unitless 0-1), fill value -999, data ends ~1-2 days before today.
Meteorology comes from GEOS-IT/MERRA-2 on a 0.5 x 0.625 degree grid (roughly 55 km x 52 km here).
"""

from datetime import date, datetime, timedelta

import httpx

from app.data_sources.base import MetricSpec
from app.models import LatLon, Metric, MetricCategory, MetricSource, Period, Quality

URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
FILL = -999.0
WINDOW_DAYS = 30
LOOKBACK_DAYS = 45  # request extra days: the newest few are fill values (processing lag)
MIN_VALID_DAYS = 25  # for means; the precipitation total needs all 30 days
RESOLUTION_M = 55_000

SRC = MetricSource(
    dataset="NASA POWER Daily (GEOS-IT / MERRA-2 meteorology)",
    provider="NASA",
    url="https://power.larc.nasa.gov/",
)
WETNESS_NOTE = (
    "Modeled by NASA's GEOS land model, not measured by satellite. 0 = completely dry, "
    "1 = saturated. This is relative wetness, not volumetric soil moisture. Grid cell ~55 km."
)
COARSE_NOTE = "Grid cell is about 55 km across, much larger than a field."

SPECS = {
    "RH2M": MetricSpec("relative_humidity_2m", "Relative humidity (2 m, 30-day mean)",
                       MetricCategory.atmosphere, "%", Quality.modeled, SRC, RESOLUTION_M, COARSE_NOTE),
    "T2M": MetricSpec("air_temp_mean_2m", "Air temperature (2 m, 30-day mean)",
                      MetricCategory.temperature, "degC", Quality.modeled, SRC, RESOLUTION_M, COARSE_NOTE),
    "PRECTOTCORR": MetricSpec("precip_30d_total", "Precipitation (30-day total)",
                              MetricCategory.precipitation, "mm", Quality.modeled, SRC, RESOLUTION_M,
                              COARSE_NOTE),
    "GWETTOP": MetricSpec("soil_wetness_surface", "Surface soil wetness (modeled, 30-day mean)",
                          MetricCategory.moisture, "fraction", Quality.modeled, SRC, RESOLUTION_M,
                          WETNESS_NOTE),
    "GWETROOT": MetricSpec("soil_wetness_rootzone", "Root-zone soil wetness (modeled, 30-day mean)",
                           MetricCategory.moisture, "fraction", Quality.modeled, SRC, RESOLUTION_M,
                           WETNESS_NOTE),
}


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y%m%d").date()


class PowerSource:
    name = "nasa_power"
    specs = list(SPECS.values())

    def __init__(self, today: date | None = None):
        self._today = today

    def params(self, anchor: LatLon) -> dict:
        today = self._today or date.today()
        end = today - timedelta(days=1)
        start = end - timedelta(days=LOOKBACK_DAYS)
        return {
            "parameters": ",".join(SPECS),
            "community": "AG",
            "longitude": round(anchor.lon, 4),
            "latitude": round(anchor.lat, 4),
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "format": "JSON",
            "time-standard": "UTC",
        }

    async def fetch(self, client: httpx.AsyncClient, anchor: LatLon) -> list[Metric]:
        r = await client.get(URL, params=self.params(anchor))
        r.raise_for_status()
        data = r.json()["properties"]["parameter"]
        fill = r.json().get("header", {}).get("fill_value", FILL)

        def valid(v) -> bool:
            return v is not None and v != fill

        # Window ends at the newest day where every parameter has data.
        days = sorted(set.intersection(*(set(data.get(p, {})) for p in SPECS)))
        complete = [d for d in days if all(valid(data[p][d]) for p in SPECS)]
        if not complete:
            return [s.unavailable("NASA POWER returned no recent data for this point.")
                    for s in SPECS.values()]
        end = _d(complete[-1])
        start = end - timedelta(days=WINDOW_DAYS - 1)
        window = [d for d in days if start <= _d(d) <= end]
        period = Period(start=start, end=end)

        out: list[Metric] = []
        for param, spec in SPECS.items():
            vals = [data[param][d] for d in window if valid(data[param][d])]
            if param == "PRECTOTCORR":
                if len(vals) < WINDOW_DAYS:
                    out.append(spec.unavailable(
                        f"Only {len(vals)} of {WINDOW_DAYS} days of precipitation available."))
                    continue
                value = round(sum(vals), 1)
            else:
                if len(vals) < MIN_VALID_DAYS:
                    out.append(spec.unavailable(
                        f"Only {len(vals)} of {WINDOW_DAYS} days available from NASA POWER."))
                    continue
                mean = sum(vals) / len(vals)
                value = round(mean, 3 if spec.unit == "fraction" else 1)
            out.append(spec.metric(value, as_of=end, period=period))
        return out
