"""Farmer context: real HTTP clients with mocked upstream services; no PostGIS needed."""

import asyncio
import json
from datetime import date

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.field_info import sources
from app.field_info.service import FieldInfoService
from app.main import create_app
from app.models import LatLon
from tests.contract import BASE_URL, assert_matches_contract

POINT = {"lat": 41.98, "lon": -93.7}
SOIL = {"Table": [
    ["soil_name", "texture", "drainage", "organic_matter", "ph"],
    ["Clarion", "Loam", "Well drained", "4.5", "6.8"],
]}


def climate_payload(*, normal=False):
    keys = [f"{year}{month:02d}" for year in (2023, 2024, 2025, 2026) for month in range(1, 13)]
    if normal:
        keys = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    return {
        "properties": {"parameter": {
            "T2M": dict.fromkeys(keys, 10), "PRECTOTCORR": dict.fromkeys(keys, 2),
            "ALLSKY_SFC_SW_DWN": dict.fromkeys(keys, 15),
        }},
        "header": {"fill_value": -999,
                   "range": "25-year Meteorological and Solar Monthly & Annual Climatologies "
                            "(January 2001 - December 2025)"},
        "parameters": {"T2M": {"units": "C"}, "PRECTOTCORR": {"units": "mm/day"},
                       "ALLSKY_SFC_SW_DWN": {"units": "MJ/m^2/day"}},
    }


def mock_sources(router):
    return {
        "recent": router.get(sources.MONTHLY_URL).respond(200, json=climate_payload()),
        "normal": router.get(sources.NORMAL_URL).respond(200, json=climate_payload(normal=True)),
        "soil": router.post(sources.ssurgo.URL).respond(200, json=SOIL),
        "terrain": router.get(sources.elevation.URL).respond(200, json={"value": "250", "resolution": 10}),
        "land": router.get(sources.NLCD_URL).respond(200, json={
            "features": [{"properties": {"PALETTE_INDEX": 82}}]}),
    }


@pytest.fixture
def info_client(tmp_path):
    # Prove this endpoint works without prepared GIS data or a database.
    settings = Settings(data_dir=tmp_path / "absent", cache_dir=tmp_path / "cache",
                        database_url="", log_level="WARNING", stub_duration_s=0)
    with TestClient(create_app(settings), base_url=BASE_URL) as client:
        yield client


def by_key(metrics):
    return {m.key: m for m in metrics}


@pytest.mark.contract
def test_endpoint_and_rounded_cache(info_client):
    with respx.mock as router:
        routes = mock_sources(router)
        first = info_client.post("/v1/fields/info", json={"point": POINT})
        assert first.status_code == 200
        assert_matches_contract(first)
        body = first.json()
        metrics = {m["key"]: m for m in body["metrics"]}
        assert len(metrics) == 14
        assert all(m["value"] is not None and m["label"] and m["unit"] for m in metrics.values())
        assert all(m["unavailable_reason"] is None for m in metrics.values())
        assert metrics["soil_drainage"]["value"] == "Well drained"
        assert metrics["land_cover"]["value"] == "Cultivated crops"
        assert metrics["slope"]["value"] == 0
        assert not body["cached"]
        counts = {key: route.call_count for key, route in routes.items()}
        second = info_client.post("/v1/fields/info", json={"point": {"lat": 41.98001, "lon": -93.70001}})
        assert_matches_contract(second)
        assert second.json()["cached"]
        assert second.json()["point"] == POINT
        assert second.json()["metrics"] == body["metrics"]
        assert {key: route.call_count for key, route in routes.items()} == counts
        info_client.post("/v1/fields/info", json={"point": {"lat": 41.981, "lon": -93.7}})
        assert routes["soil"].call_count == 2
        query = json.loads(routes["soil"].calls[0].request.content)["query"]
        assert "point(-93.700000 41.980000)" in query


@pytest.mark.parametrize("point", [
    POINT, {"lat": 40, "lon": -89}, {"lat": 41, "lon": -100},
])
def test_supported_states(info_client, point):
    with respx.mock as router:
        mock_sources(router)
        assert info_client.post("/v1/fields/info", json={"point": point}).status_code == 200


@pytest.mark.contract
@pytest.mark.parametrize("point", [
    {"lat": 30.2672, "lon": -97.7431}, {"lat": 45, "lon": -93},
    {"lat": 0, "lon": 0}, {"lat": 41, "lon": -105},
])
def test_outside_coverage_never_fetches(info_client, point):
    with respx.mock as router:
        response = info_client.post("/v1/fields/info", json={"point": point})
        assert response.status_code == 422
        assert_matches_contract(response)
        assert response.json()["error"]["code"] == "OUTSIDE_COVERAGE"
        assert "Iowa, Illinois and Nebraska" in response.json()["error"]["message"]
        assert not router.calls


@pytest.mark.parametrize("body", [{}, {"point": {"lat": 91, "lon": 0}},
                                       {"point": {"lat": 41}}, {"point": POINT, "extra": 1},
                                       {"point": {"lat": "NaN", "lon": -93}}])
def test_invalid_input(info_client, body):
    response = info_client.post("/v1/fields/info", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.contract
def test_partial_failure_retries_failed_source_only(info_client):
    with respx.mock as router:
        routes = mock_sources(router)
        routes["soil"].respond(503)
        first = info_client.post("/v1/fields/info", json={"point": POINT})
        assert_matches_contract(first)
        metrics = {m["key"]: m for m in first.json()["metrics"]}
        assert metrics["soil_ph"]["value"] is None
        assert metrics["soil_ph"]["unavailable_reason"]
        assert metrics["temperature_12m"]["value"] == 10
        assert metrics["land_cover"]["value"] == "Cultivated crops"
        routes["soil"].respond(200, json=SOIL)
        second = info_client.post("/v1/fields/info", json={"point": POINT})
        assert all(m["value"] is not None for m in second.json()["metrics"])
        assert routes["soil"].call_count == 2
        assert routes["recent"].call_count == routes["normal"].call_count == routes["land"].call_count == 1


@pytest.mark.contract
def test_total_outage_still_returns_context_shape(info_client):
    with respx.mock as router:
        routes = mock_sources(router)
        for route in routes.values():
            route.respond(200, json={"unexpected": "payload"})
        response = info_client.post("/v1/fields/info", json={"point": POINT})
        assert response.status_code == 200
        assert_matches_contract(response)
        assert len(response.json()["metrics"]) == 14
        assert all(m["value"] is None and m["unavailable_reason"] for m in response.json()["metrics"])


async def test_recent_weighting_leap_year_and_publication_lag():
    payload = climate_payload()
    params = payload["properties"]["parameter"]
    # February 2024 contributes 29 days, not 1/12 of the year.
    params["T2M"]["202402"] = 39
    # Solar can lag meteorology while keeping its own complete, honest window.
    params["ALLSKY_SFC_SW_DWN"]["202412"] = -999
    with respx.mock as router:
        route = router.get(sources.MONTHLY_URL).respond(200, json=payload)
        async with httpx.AsyncClient() as client:
            metrics = by_key(await sources.fetch_power_recent(
                client, LatLon(**POINT), today=date(2025, 1, 15)))
    assert metrics["precipitation_12m"].value == 732  # 2 mm/day * 366 days
    assert metrics["temperature_12m"].value == round(10 + 29 * 29 / 366, 1)
    assert str(metrics["temperature_12m"].period.end) == "2024-12-31"
    assert str(metrics["solar_radiation_12m"].period.end) == "2024-11-30"
    assert "202413" not in str(metrics)  # POWER's annual aggregate must not become a thirteenth month.
    assert route.calls[0].request.url.params["community"] == "AG"


async def test_power_missing_month_and_unit_conversion():
    payload = climate_payload()
    payload["properties"]["parameter"]["PRECTOTCORR"]["202406"] = -999
    payload["parameters"]["ALLSKY_SFC_SW_DWN"]["units"] = "kW-hr/m^2/day"
    with respx.mock as router:
        router.get(sources.MONTHLY_URL).respond(200, json=payload)
        async with httpx.AsyncClient() as client:
            metrics = by_key(await sources.fetch_power_recent(
                client, LatLon(**POINT), today=date(2025, 1, 1)))
    assert metrics["precipitation_12m"].value is None
    assert metrics["precipitation_12m"].unavailable_reason
    assert metrics["temperature_12m"].value == 10
    assert metrics["solar_radiation_12m"].value == 54


async def test_long_term_baseline_comes_from_nasa():
    with respx.mock as router:
        router.get(sources.NORMAL_URL).respond(200, json=climate_payload(normal=True))
        async with httpx.AsyncClient() as client:
            metrics = by_key(await sources.fetch_power_normal(client, LatLon(**POINT)))
    assert metrics["precipitation_normal"].value == 730.5
    assert metrics["temperature_normal"].period.start == date(2001, 1, 1)
    assert metrics["temperature_normal"].period.end == date(2025, 12, 31)


async def test_partial_soil_and_land_cover_nodata():
    with respx.mock as router:
        router.post(sources.ssurgo.URL).respond(200, json={"Table": [SOIL["Table"][0],
            ["Clarion", "Loam", None, "0", "NaN"]]})
        land_route = router.get(sources.NLCD_URL).respond(200, json={
            "features": [{"properties": {"PALETTE_INDEX": 0}}]})
        async with httpx.AsyncClient() as client:
            metrics = by_key(await sources.fetch_soil(client, LatLon(**POINT)))
            land = await sources.fetch_land_cover(client, LatLon(**POINT))
    assert metrics["dominant_soil"].value == "Clarion"
    assert metrics["soil_organic_matter"].value == 0
    assert metrics["soil_drainage"].value is metrics["soil_ph"].value is None
    assert land[0].value is None
    assert land[0].unavailable_reason
    assert land_route.calls[0].request.url.params["time"] == "2024-01-01"


@pytest.mark.parametrize("missing_neighbor", [False, True])
async def test_terrain_gradient_and_missing_neighbor(missing_neighbor):
    def answer(request):
        lon = float(request.url.params["x"])
        lat = float(request.url.params["y"])
        if missing_neighbor and lon > POINT["lon"] + 0.0001:
            return httpx.Response(503)
        # A plane increasing eastward at 5%, computed using true geodesic distances.
        azimuth, _, distance = sources.Geod(ellps="WGS84").inv(POINT["lon"], POINT["lat"], lon, lat)
        east_distance = distance * sources.math.sin(sources.math.radians(azimuth))
        return httpx.Response(200, json={"value": 250 + east_distance * 0.05, "resolution": 10})

    with respx.mock as router:
        router.get(sources.elevation.URL).mock(side_effect=answer)
        async with httpx.AsyncClient() as client:
            metrics = by_key(await sources.fetch_terrain(client, LatLon(**POINT)))
    assert metrics["elevation"].value == 250
    assert metrics["slope"].value == (None if missing_neighbor else 5)


async def test_sources_start_concurrently_and_timeout_is_isolated():
    started = set()
    all_started = asyncio.Event()

    async def answer(request):
        started.add(str(request.url).split("?")[0])
        if len(started) == 5:
            all_started.set()
        await all_started.wait()  # Sequential fetching would time out without producing any data.
        if str(request.url).startswith(sources.ssurgo.URL):
            await asyncio.Event().wait()
        if str(request.url).startswith(sources.MONTHLY_URL):
            return httpx.Response(200, json=climate_payload())
        if str(request.url).startswith(sources.NORMAL_URL):
            return httpx.Response(200, json=climate_payload(normal=True))
        if str(request.url).startswith(sources.elevation.URL):
            return httpx.Response(200, json={"value": 250})
        return httpx.Response(200, json={"features": [{"properties": {"PALETTE_INDEX": 82}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
        service = FieldInfoService(client, timeout_s=0.1)
        result = await service.info(LatLon(**POINT))
        await service.aclose()
    metrics = by_key(result.metrics)
    assert len(started) == 5
    assert metrics["temperature_12m"].value == 10
    assert metrics["soil_ph"].value is None
    assert "in time" in metrics["soil_ph"].unavailable_reason
    assert metrics["land_cover"].value == "Cultivated crops"


async def test_slow_terrain_finishes_once_and_is_cached(monkeypatch):
    release = asyncio.Event()
    calls = 0

    async def slow_terrain(client, point):
        nonlocal calls
        calls += 1
        await release.wait()
        return [sources.TERRAIN_SPECS[0].metric(250), sources.TERRAIN_SPECS[1].metric(5)]

    monkeypatch.setattr(sources, "fetch_terrain", slow_terrain)
    with respx.mock(assert_all_called=False) as router:
        mock_sources(router)
        async with httpx.AsyncClient() as client:
            service = FieldInfoService(client, timeout_s=0.01)
            first = await service.info(LatLon(**POINT))
            assert by_key(first.metrics)["elevation"].value is None
            second = await service.info(LatLon(**POINT))
            assert not second.cached
            assert calls == 1  # Repeated requests must join the existing slow fetch.
            release.set()
            recovered = await service.info(LatLon(**POINT))
            assert by_key(recovered.metrics)["elevation"].value == 250
            assert by_key(recovered.metrics)["slope"].value == 5
            cached = await service.info(LatLon(**POINT))
            assert cached.cached
            assert calls == 1


async def test_terrain_accepts_responses_after_old_sample_deadline():
    async def slow(request):
        await asyncio.sleep(3.6)
        return httpx.Response(200, json={"value": 250, "resolution": 10})

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        metrics = by_key(await sources.fetch_terrain(client, LatLon(**POINT)))
    assert metrics["elevation"].value == 250
    assert metrics["slope"].value == 0
