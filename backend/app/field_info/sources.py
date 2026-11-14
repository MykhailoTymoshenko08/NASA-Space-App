"""Small point queries; each async fetch function is reusable without FastAPI.

Dataset documentation is linked in backend/README.md. POWER uses monthly means in
community AG units; precipitation rates must be multiplied by days, never summed as totals.
NLCD uses the public MRLC WMS GetFeatureInfo endpoint, not downloaded raster tiles.
"""

import asyncio
import calendar
import math
import re
from datetime import date, timedelta

import httpx
from pyproj import Geod

from app.data_sources import elevation, ssurgo
from app.data_sources.base import MetricSpec
from app.models import LatLon, Metric, MetricCategory, MetricSource, Period, Quality

HTTP_TIMEOUT = httpx.Timeout(3.5, connect=1.5)
MONTHLY_URL = "https://power.larc.nasa.gov/api/temporal/monthly/point"
NORMAL_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"
NLCD_URL = "https://dmsdata.cr.usgs.gov/geoserver/mrlc_Land-Cover-Native_conus_year_data/wms"
NLCD_LAYER = "Land-Cover-Native_conus_year_data"
NLCD_YEAR = 2024
SAMPLE_DISTANCE_M = 100
POWER_SOURCE = MetricSource(dataset="NASA POWER Monthly / Climatology", provider="NASA",
                            url="https://power.larc.nasa.gov/")


def _climate_specs(suffix: str, period_label: str) -> list[MetricSpec]:
    return [
        MetricSpec(f"temperature_{suffix}", f"Average temperature ({period_label})",
                   MetricCategory.temperature, "degC", Quality.modeled, POWER_SOURCE, 55_000),
        MetricSpec(f"precipitation_{suffix}", f"Annual precipitation ({period_label})",
                   MetricCategory.precipitation, "mm", Quality.modeled, POWER_SOURCE, 55_000),
        MetricSpec(f"solar_radiation_{suffix}", f"Daily sunlight energy ({period_label})",
                   MetricCategory.atmosphere, "MJ/m²/day", Quality.modeled, POWER_SOURCE, 100_000),
    ]


RECENT_SPECS = _climate_specs("12m", "latest 12 available months")
NORMAL_SPECS = _climate_specs("normal", "long-term average")
PARAMETERS = ("T2M", "PRECTOTCORR", "ALLSKY_SFC_SW_DWN")
SOIL_SPECS = [
    MetricSpec("dominant_soil", "Dominant soil name", MetricCategory.soil,
               "none", Quality.estimated, ssurgo.SRC, None),
    MetricSpec("soil_texture", "Surface soil texture", MetricCategory.soil,
               "class", Quality.estimated, ssurgo.SRC, None),
    MetricSpec("soil_drainage", "Soil drainage class", MetricCategory.soil,
               "class", Quality.estimated, ssurgo.SRC, None),
    MetricSpec("soil_organic_matter", "Surface soil organic matter", MetricCategory.soil,
               "%", Quality.estimated, ssurgo.SRC, None),
    MetricSpec("soil_ph", "Surface soil pH", MetricCategory.soil,
               "pH", Quality.estimated, ssurgo.SRC, None),
]
TERRAIN_SPECS = [
    MetricSpec("elevation", "Elevation above sea level", MetricCategory.terrain,
               "m", Quality.measured, elevation.SRC, None),
    MetricSpec("slope", "Approximate local slope", MetricCategory.terrain,
               "%", Quality.estimated, elevation.SRC, None),
]
LAND_SPEC = MetricSpec(
    "land_cover", f"Land cover ({NLCD_YEAR})", MetricCategory.vegetation,
    "class", Quality.modeled,
    MetricSource(dataset=f"Annual NLCD {NLCD_YEAR} Land Cover", provider="USGS / MRLC",
                 url="https://www.mrlc.gov/data-services-page"), 30,
)
LAND_CLASSES = {
    11: "Open water", 12: "Perennial ice or snow", 21: "Developed, open space",
    22: "Developed, low intensity", 23: "Developed, medium intensity", 24: "Developed, high intensity",
    31: "Barren land", 41: "Deciduous forest", 42: "Evergreen forest", 43: "Mixed forest",
    51: "Dwarf scrub", 52: "Shrub or scrub", 71: "Grassland or herbaceous",
    72: "Sedge or herbaceous", 73: "Lichens", 74: "Moss", 81: "Pasture or hay",
    82: "Cultivated crops", 90: "Woody wetlands", 95: "Emergent herbaceous wetlands",
}

# Pick the dominant component before joining a horizon, so a missing horizon does not
# replace the dominant soil with a smaller component or discard its name/drainage.
SOIL_QUERY = """SELECT TOP 1 c.compname AS soil_name, tg.texdesc AS texture,
    c.drainagecl AS drainage, ch.om_r AS organic_matter, ch.ph1to1h2o_r AS ph
FROM component c
OUTER APPLY (SELECT TOP 1 h.chkey, h.om_r, h.ph1to1h2o_r FROM chorizon h
    WHERE h.cokey = c.cokey ORDER BY h.hzdept_r, h.chkey) ch
LEFT JOIN chtexturegrp tg ON tg.chkey = ch.chkey AND tg.rvindicator = 'Yes'
WHERE c.mukey IN (SELECT * FROM
    SDA_Get_Mukey_from_intersection_with_WktWgs84('point({lon} {lat})'))
ORDER BY c.comppct_r DESC, c.cokey
"""


def _number(value, fill: float = -999) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) and n != fill else None
    except (TypeError, ValueError):
        return None


async def _power_payload(client: httpx.AsyncClient, url: str, point: LatLon, **params) -> dict:
    response = await client.get(url, params={
        "latitude": point.lat, "longitude": point.lon, "community": "AG",
        "parameters": ",".join(PARAMETERS), "format": "JSON", **params,
    }, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _power_value(payload: dict, param: str, key: str) -> float | None:
    value = _number(payload.get("properties", {}).get("parameter", {}).get(param, {}).get(key),
                    payload.get("header", {}).get("fill_value", -999))
    if value is None:
        return None
    unit = payload.get("parameters", {}).get(param, {}).get("units")
    if param == "ALLSKY_SFC_SW_DWN":
        if unit in ("kW-hr/m^2/day", "kWh/m^2/day"):
            value *= 3.6
        elif unit != "MJ/m^2/day":
            return None
    elif unit not in (("C", "degC") if param == "T2M" else ("mm/day",)):
        return None
    return None if param != "T2M" and value < 0 else value


def _month(offset: int) -> date:
    """Convert year * 12 + zero-based month to its first day."""
    year, month = divmod(offset, 12)
    return date(year, month + 1, 1)


async def fetch_power_recent(
    client: httpx.AsyncClient, point: LatLon, *, today: date | None = None,
) -> list[Metric]:
    today = today or date.today()
    payload = await _power_payload(client, MONTHLY_URL, point, start=today.year - 2, end=today.year)
    latest = today.year * 12 + today.month - 2  # exclude the current, incomplete month
    metrics = []
    for param, spec in zip(PARAMETERS, RECENT_SPECS, strict=True):
        # Parameters publish at different times. Accept up to six months of publication lag.
        end = next((m for m in range(latest, latest - 6, -1)
                    if _power_value(payload, param, _month(m).strftime("%Y%m")) is not None), None)
        if end is None:
            metrics.append(spec.unavailable("No recent complete monthly data from NASA POWER."))
            continue
        months = [_month(m) for m in range(end - 11, end + 1)]
        values = [_power_value(payload, param, m.strftime("%Y%m")) for m in months]
        if any(v is None for v in values):
            metrics.append(spec.unavailable("NASA POWER is missing months in the 12-month window."))
            continue
        days = [calendar.monthrange(m.year, m.month)[1] for m in months]
        total = sum(v * d for v, d in zip(values, days, strict=True))
        value = total if param == "PRECTOTCORR" else total / sum(days)
        period = Period(start=months[0], end=_month(end + 1) - timedelta(days=1))
        metrics.append(spec.metric(round(value, 1), period=period, as_of=period.end,
                                   note="Regional climate context; grid cells are much larger than a field."))
    return metrics


async def fetch_power_normal(client: httpx.AsyncClient, point: LatLon) -> list[Metric]:
    payload = await _power_payload(client, NORMAL_URL, point)
    baseline = payload.get("header", {}).get("range", "")
    match = re.search(r"January (\d{4}) - December (\d{4})", baseline)
    period = None
    if match:
        first, last = map(int, match.groups())
        period = Period(start=date(first, 1, 1), end=date(last, 12, 31))
        leap_days = sum(calendar.isleap(y) for y in range(first, last + 1)) / (last - first + 1)
    else:
        leap_days = 0.2425
    days = [calendar.monthrange(2001, m)[1] + (leap_days if m == 2 else 0) for m in range(1, 13)]
    metrics = []
    for param, spec in zip(PARAMETERS, NORMAL_SPECS, strict=True):
        values = [_power_value(payload, param, calendar.month_abbr[m].upper()) for m in range(1, 13)]
        if any(v is None for v in values):
            metrics.append(spec.unavailable("NASA POWER has incomplete long-term monthly averages."))
            continue
        total = sum(v * d for v, d in zip(values, days, strict=True))
        value = total if param == "PRECTOTCORR" else total / sum(days)
        metrics.append(spec.metric(round(value, 1), period=period,
                                   note=baseline or "NASA climatology; baseline dates were not reported."))
    return metrics


async def fetch_soil(client: httpx.AsyncClient, point: LatLon) -> list[Metric]:
    response = await client.post(ssurgo.URL, json={
        "query": SOIL_QUERY.format(lon=f"{point.lon:.6f}", lat=f"{point.lat:.6f}"),
        "format": "JSON+COLUMNNAME",
    }, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    table = response.json().get("Table") or []
    row = dict(zip(table[0], table[1], strict=False)) if len(table) > 1 else {}
    metrics = []
    columns = ("soil_name", "texture", "drainage", "organic_matter", "ph")
    for spec, key in zip(SOIL_SPECS, columns, strict=True):
        raw = row.get(key)
        value = _number(raw) if key in ("organic_matter", "ph") else (str(raw).strip() if raw else None)
        if value == "":
            value = None
        metrics.append(spec.metric(value,
                                   note=ssurgo.BASE_NOTE,
                                   unavailable_reason="No soil survey value at this point."
                                   if value is None else None))
    return metrics


async def fetch_terrain(client: httpx.AsyncClient, point: LatLon) -> list[Metric]:
    async def sample(lon: float, lat: float) -> tuple[float | None, float | None]:
        try:
            # Bound each sample separately, preserving the centre if a neighbour fails.
            async with asyncio.timeout(3.5):
                response = await client.get(elevation.URL, params={
                    "x": lon, "y": lat, "wkid": 4326, "units": "Meters", "includeDate": "false",
                }, timeout=HTTP_TIMEOUT)
                response.raise_for_status()
                payload = response.json()
                value = _number(payload.get("value"))
                if value is None or value <= elevation.NODATA:
                    return None, None
                return value, _number(payload.get("resolution"))
        except Exception:  # A missing sample only removes its elevation/slope metric.
            return None, None

    geod = Geod(ellps="WGS84")
    neighbors = [geod.fwd(point.lon, point.lat, azimuth, SAMPLE_DISTANCE_M)[:2]
                 for azimuth in (0, 90, 180, 270)]
    center, north, east, south, west = await asyncio.gather(
        sample(point.lon, point.lat), *(sample(lon, lat) for lon, lat in neighbors))
    height, resolution = center
    height_metric = TERRAIN_SPECS[0].metric(
        round(height, 1) if height is not None else None, resolution_m=resolution,
        unavailable_reason="3DEP elevation did not return a value in time." if height is None else None)
    if all(v[0] is not None for v in (north, east, south, west)):
        dz_dx = (east[0] - west[0]) / (2 * SAMPLE_DISTANCE_M)
        dz_dy = (north[0] - south[0]) / (2 * SAMPLE_DISTANCE_M)
        slope = round(100 * math.hypot(dz_dx, dz_dy), 1)
        slope_metric = TERRAIN_SPECS[1].metric(
            slope, note="Estimated from 3DEP samples 100 m north, east, south and west; not a field average.")
    else:
        slope_metric = TERRAIN_SPECS[1].unavailable(
            "Slope needs four nearby elevation samples; some are unavailable.")
    return [height_metric, slope_metric]


async def fetch_land_cover(client: httpx.AsyncClient, point: LatLon) -> list[Metric]:
    delta = 0.0001
    response = await client.get(NLCD_URL, params={
        "service": "WMS", "version": "1.1.1", "request": "GetFeatureInfo",
        "layers": NLCD_LAYER, "query_layers": NLCD_LAYER, "srs": "EPSG:4326",
        "bbox": f"{point.lon - delta},{point.lat - delta},{point.lon + delta},{point.lat + delta}",
        "width": 3, "height": 3, "x": 1, "y": 1, "info_format": "application/json",
        "time": f"{NLCD_YEAR}-01-01",
    }, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    features = response.json().get("features") or []
    code = _number(features[0].get("properties", {}).get("PALETTE_INDEX")) if features else None
    label = LAND_CLASSES.get(code)
    reason = "No NLCD land-cover class at this point." if not label else None
    return [LAND_SPEC.metric(label, note=f"30 m land-cover class at the point; NLCD code {int(code)}."
                             if label else None, as_of=date(NLCD_YEAR, 12, 31),
                             unavailable_reason=reason)]
