"""M4: data source clients and POST /snapshots. Upstreams are mocked with respx."""

import asyncio
from datetime import date, timedelta

import httpx
import pytest
import respx

from app.data_sources import elevation, power, soilgrids, ssurgo
from app.data_sources.power import PowerSource
from app.models import FieldSelection, LatLon
from tests.contract import assert_matches_contract
from tests.fixture_data import F1_POINT

ALL_KEYS = {
    "relative_humidity_2m", "air_temp_mean_2m", "precip_30d_total", "soil_wetness_surface",
    "soil_wetness_rootzone", "soil_organic_matter_pct", "soil_ph", "soil_texture_class",
    "elevation_m", "soil_nitrogen_total",
}
ANCHOR = LatLon(lat=41.6, lon=-93.6)


def selection(boundary: str = "plss_section") -> FieldSelection:
    ring = [[-93.61, 41.59], [-93.59, 41.59], [-93.59, 41.61], [-93.61, 41.61], [-93.61, 41.59]]
    sec = boundary == "plss_section"
    return FieldSelection(
        field_id="plss:IA050790N0240W0SN140" if sec else None, anchor=ANCHOR,
        geometry={"type": "Polygon", "coordinates": [ring]}, bbox=[-93.61, 41.59, -93.59, 41.61],
        resolved_by="field_polygon" if sec else "buffered_point", boundary_type=boundary,
        area_ha=259.0, county={"fips": "19153", "name": "Polk", "state_postal": "IA"},
        source="map_click",
    )


SEL = selection()


def power_payload(end: date, days: int = 45, lag: int = 2, overrides=None) -> dict:
    """Daily POWER-like payload; the last `lag` days are fill values (-999)."""
    params = {"RH2M": 80.0, "T2M": 10.0, "PRECTOTCORR": 2.0, "GWETTOP": 0.6, "GWETROOT": 0.7}
    out = {}
    for p, v in params.items():
        series = {}
        for i in range(days):
            d = end - timedelta(days=days - 1 - i)
            series[d.strftime("%Y%m%d")] = -999.0 if i >= days - lag else v
        out[p] = series
    for (p, d), v in (overrides or {}).items():
        out[p][d] = v
    return {"header": {"fill_value": -999.0}, "properties": {"parameter": out}}


# Area query: one row per soil map unit clipped to the section, dom = 'name|pct|om|ph|texture'.
SSURGO_OK = {"Table": [
    ["mukey", "area", "dom"],
    ["1", "3.0E-05", "Clarion|85|3.0|6.0|Loam"],
    ["2", "1.0E-05", "Webster|90|5.0|7.0|Clay loam"],
]}
SSURGO_POINT = {"Table": [["mukey", "area", "dom"], ["9", "1", "Nicollet|90|4.5|6.8|Loam"]]}
EPQS_OK = {"value": "276.2", "resolution": 1}
SOILGRIDS_OK = {"properties": {"layers": [{
    "name": "nitrogen", "unit_measure": {"d_factor": 100},
    "depths": [{"label": "0-5cm", "values": {"mean": 291}}],
}]}}


def mock_all(router, **override):
    end = date.today() - timedelta(days=1)
    routes = {
        "power": router.get(power.URL).mock(
            return_value=httpx.Response(200, json=power_payload(end))),
        "ssurgo": router.post(ssurgo.URL).mock(return_value=httpx.Response(200, json=SSURGO_OK)),
        "elevation": router.get(elevation.URL).mock(return_value=httpx.Response(200, json=EPQS_OK)),
        "soilgrids": router.get(soilgrids.URL).mock(
            return_value=httpx.Response(200, json=SOILGRIDS_OK)),
    }
    for name, resp in override.items():
        if isinstance(resp, httpx.Response):
            routes[name].mock(return_value=resp)
        else:
            routes[name].mock(side_effect=resp)
    return routes


def by_key(snapshot) -> dict:
    return {m["key"]: m for m in snapshot["metrics"]}


# ---------------------------------------------------------------------------
# Source parsing
# ---------------------------------------------------------------------------
@respx.mock
async def test_power_window_skips_fill_days():
    end = date(2026, 11, 13)
    respx.get(power.URL).mock(return_value=httpx.Response(200, json=power_payload(end, lag=2)))
    async with httpx.AsyncClient() as c:
        ms = await PowerSource(today=end + timedelta(days=1)).fetch(c, SEL)
    m = {x.key: x for x in ms}
    assert m["precip_30d_total"].value == 60.0  # 30 days x 2 mm
    assert m["relative_humidity_2m"].value == 80.0
    assert m["soil_wetness_surface"].unit == "fraction"
    assert m["soil_wetness_surface"].quality == "modeled"
    newest = end - timedelta(days=2)
    assert m["air_temp_mean_2m"].period.end == newest
    assert m["air_temp_mean_2m"].period.start == newest - timedelta(days=29)
    assert m["air_temp_mean_2m"].as_of == newest
    # The request uses lon/lat as separate named params (no order mix-up).
    q = respx.calls.last.request.url.params
    assert q["latitude"] == "41.6" and q["longitude"] == "-93.6"
    assert q["parameters"] == "RH2M,T2M,PRECTOTCORR,GWETTOP,GWETROOT"


@respx.mock
async def test_power_missing_precip_day_makes_total_unavailable():
    end = date(2026, 11, 13)
    gap = (end - timedelta(days=10)).strftime("%Y%m%d")
    payload = power_payload(end, lag=0, overrides={("PRECTOTCORR", gap): -999.0})
    respx.get(power.URL).mock(return_value=httpx.Response(200, json=payload))
    async with httpx.AsyncClient() as c:
        ms = {x.key: x for x in await PowerSource(today=end + timedelta(days=1)).fetch(c, SEL)}
    # Window ends at the newest day where all params are valid, so the gap day is skipped there,
    # but the total over 30 days would undercount: it must not be invented.
    assert ms["precip_30d_total"].quality == "unavailable"
    assert ms["precip_30d_total"].value is None
    assert ms["relative_humidity_2m"].value == 80.0


@respx.mock
async def test_ssurgo_no_data_is_unavailable():
    respx.post(ssurgo.URL).mock(return_value=httpx.Response(200, json={}))
    async with httpx.AsyncClient() as c:
        ms = await ssurgo.SsurgoSource().fetch(c, SEL)
    assert all(m.quality == "unavailable" and m.unavailable_reason for m in ms)


@respx.mock
async def test_ssurgo_area_weighted_over_section():
    route = respx.post(ssurgo.URL).mock(return_value=httpx.Response(200, json=SSURGO_OK))
    async with httpx.AsyncClient() as c:
        ms = {m.key: m for m in await ssurgo.SsurgoSource().fetch(c, SEL)}
    # weights 3:1 -> OM (3*3 + 5*1)/4 = 3.5, pH (6*3 + 7*1)/4 = 6.25 -> 6.2; texture: largest area.
    assert ms["soil_organic_matter_pct"].value == 3.5
    assert ms["soil_ph"].value == 6.2
    assert ms["soil_texture_class"].value == "Loam"
    assert "Area-weighted over the survey section" in ms["soil_ph"].note
    body = route.calls.last.request.content.decode()
    assert "GetClippedMapunits" in body and "POLYGON ((-93.61 41.59" in body  # lon lat order
    assert route.call_count == 1


@respx.mock
async def test_ssurgo_falls_back_to_point_when_area_query_fails():
    route = respx.post(ssurgo.URL).mock(side_effect=[
        httpx.Response(500), httpx.Response(200, json=SSURGO_POINT)])
    async with httpx.AsyncClient() as c:
        ms = {m.key: m for m in await ssurgo.SsurgoSource().fetch(c, SEL)}
    assert ms["soil_organic_matter_pct"].value == 4.5
    assert "anchor point" in ms["soil_ph"].note and "failed" in ms["soil_ph"].note
    assert "point(-93.600000 41.600000)" in route.calls.last.request.content.decode()


@respx.mock
async def test_ssurgo_buffered_point_uses_point_query():
    route = respx.post(ssurgo.URL).mock(return_value=httpx.Response(200, json=SSURGO_POINT))
    async with httpx.AsyncClient() as c:
        ms = {m.key: m for m in await ssurgo.SsurgoSource().fetch(c, selection("buffered_point"))}
    assert route.call_count == 1
    assert "GetClippedMapunits" not in route.calls.last.request.content.decode()
    assert ms["soil_texture_class"].value == "Loam"
    assert "selected point" in ms["soil_ph"].note


@respx.mock
async def test_soilgrids_null_mean_unavailable():
    payload = {"properties": {"layers": [{"name": "nitrogen", "unit_measure": {"d_factor": 100},
                                          "depths": [{"values": {"mean": None}}]}]}}
    respx.get(soilgrids.URL).mock(return_value=httpx.Response(200, json=payload))
    async with httpx.AsyncClient() as c:
        (m,) = await soilgrids.SoilGridsSource().fetch(c, SEL)
    assert m.quality == "unavailable" and m.value is None


@respx.mock
async def test_soilgrids_converts_cg_per_kg():
    respx.get(soilgrids.URL).mock(return_value=httpx.Response(200, json=SOILGRIDS_OK))
    async with httpx.AsyncClient() as c:
        (m,) = await soilgrids.SoilGridsSource().fetch(c, SEL)
    assert m.value == 2.91 and m.unit == "g/kg" and m.quality == "estimated"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.contract


def test_snapshot_all_sources(client):
    with respx.mock(assert_all_called=False) as router:
        mock_all(router)
        r = client.post("/v1/snapshots", json={"selection": {"field_id": "plss:IA050790N0240W0SN140"}})
    assert_matches_contract(r)
    s = r.json()
    assert s["cached"] is False
    assert s["selection"]["field_id"] == "plss:IA050790N0240W0SN140"
    m = by_key(s)
    assert set(m) == ALL_KEYS
    for metric in s["metrics"]:
        assert metric["source"]["dataset"] and metric["source"]["provider"]
        assert "resolution_m" in metric
    assert m["elevation_m"]["value"] == 276.2
    assert m["soil_texture_class"]["value"] == "Loam"
    assert m["soil_organic_matter_pct"]["value"] == 3.5
    assert m["precip_30d_total"]["period"] is not None


def test_snapshot_cached_second_time(client):
    with respx.mock(assert_all_called=False) as router:
        routes = mock_all(router)
        client.post("/v1/snapshots", json={"selection": {"field_id": "plss:IA050790N0240W0SN140"}})
        r = client.post("/v1/snapshots", json={"selection": {"field_id": "plss:IA050790N0240W0SN140"}})
        assert routes["power"].call_count == 1
    assert_matches_contract(r)
    assert r.json()["cached"] is True


def test_point_snapshot_cache_rounds_to_001_deg(client):
    with respx.mock(assert_all_called=False) as router:
        routes = mock_all(router)
        a = client.post("/v1/snapshots", json={"selection": {"point": {"lat": 41.7001, "lon": -93.7001}}})
        b = client.post("/v1/snapshots", json={"selection": {"point": {"lat": 41.7004, "lon": -93.7003}}})
        assert routes["power"].call_count == 1
    assert_matches_contract(a)
    assert a.json()["selection"]["resolved_by"] == "buffered_point"
    assert b.json()["cached"] is True
    assert b.json()["selection"]["anchor"] == {"lat": 41.7004, "lon": -93.7003}


@pytest.mark.parametrize(
    "failing",
    [
        {"power": httpx.Response(500)},
        {"ssurgo": httpx.ConnectError("down")},
        {"soilgrids": httpx.Response(503)},
        {"elevation": httpx.Response(200, text="not json")},
    ],
)
def test_one_source_down_still_200(client, failing):
    (name,) = failing
    with respx.mock(assert_all_called=False) as router:
        mock_all(router, **failing)
        r = client.post("/v1/snapshots", json={"selection": {"field_id": "plss:IA050790N0240W0SN140"}})
    assert r.status_code == 200
    assert_matches_contract(r)
    metrics = r.json()["metrics"]
    assert {m["key"] for m in metrics} == ALL_KEYS  # never omitted
    bad = [m for m in metrics if m["quality"] == "unavailable"]
    assert bad and all(m["value"] is None and m["unavailable_reason"] for m in bad)
    assert len(bad) < len(metrics)


def test_all_sources_down_still_200(client):
    with respx.mock(assert_all_called=False) as router:
        mock_all(router, power=httpx.Response(500), ssurgo=httpx.Response(500),
                 elevation=httpx.Response(500), soilgrids=httpx.Response(500))
        r = client.post("/v1/snapshots", json={"selection": {"field_id": "plss:IA050790N0240W0SN140"}})
        r2 = client.post("/v1/snapshots", json={"selection": {"field_id": "plss:IA050790N0240W0SN140"}})
    assert r.status_code == 200
    assert_matches_contract(r)
    assert all(m["quality"] == "unavailable" for m in r.json()["metrics"])
    assert r2.json()["cached"] is False  # incomplete snapshots are not cached


def test_slow_source_times_out_then_served_from_cache(make_client, data_dir):
    c = make_client(data_dir, source_timeout_s=0.2)

    async def slow(request):
        await asyncio.sleep(0.5)
        return httpx.Response(200, json=SOILGRIDS_OK)

    with respx.mock(assert_all_called=False) as router:
        mock_all(router, soilgrids=slow)
        r = c.post("/v1/snapshots", json={"selection": {"field_id": "plss:IA050790N0240W0SN140"}})
        assert_matches_contract(r)
        n = by_key(r.json())["soil_nitrogen_total"]
        assert n["quality"] == "unavailable" and "in time" in n["unavailable_reason"]
        # Background fetch finishes and fills the per-source cache.
        c.portal.call(asyncio.sleep, 0.6)
        r = c.post("/v1/snapshots", json={"selection": {"field_id": "plss:IA050790N0240W0SN140"}})
    assert by_key(r.json())["soil_nitrogen_total"]["value"] == 2.91


def test_snapshot_unknown_field_404(client):
    r = client.post("/v1/snapshots", json={"selection": {"field_id": "fld_nope000000"}})
    assert r.status_code == 404
    assert_matches_contract(r)


def test_snapshot_outside_coverage(client):
    r = client.post("/v1/snapshots", json={"selection": {"point": {"lat": 48.85, "lon": 2.35}}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "OUTSIDE_COVERAGE"
    assert_matches_contract(r)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"selection": {}},
        {"selection": {"field_id": "plss:IA050790N0240W0SN140", "point": {"lat": 41.6, "lon": -93.6}}},
        {"selection": {"point": {"lat": 141.6, "lon": -93.6}}},
    ],
)
def test_snapshot_validation(client, body):
    r = client.post("/v1/snapshots", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert_matches_contract(r)


def test_point_snapshot_inside_field_uses_field(client):
    with respx.mock(assert_all_called=False) as router:
        mock_all(router)
        r = client.post(
            "/v1/snapshots",
            json={"selection": {"point": {"lat": F1_POINT[0], "lon": F1_POINT[1]}}},
        )
    assert r.json()["selection"]["field_id"] == "plss:IA050790N0240W0SN140"
