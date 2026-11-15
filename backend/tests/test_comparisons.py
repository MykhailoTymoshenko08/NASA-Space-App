"""Field comparisons: /v1/comparisons/saved-fields (2-4 saved fields) and /v1/comparisons/area (rankings).

Snapshots, field info and Soil Data Access are replaced with fakes, so no test makes a network call.
"""

import time
import uuid
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.comparisons import soil_batch
from app.comparisons.history import summarize_history
from app.comparisons.saved import _sequence, best_of
from app.models import (
    ComparisonCell,
    ComparisonPlan,
    FieldInfo,
    FieldSelection,
    LatLon,
    Metric,
    MetricCategory,
    MetricSource,
    Quality,
    RotationBudgetOptions,
    Snapshot,
    ValueRange,
)
from app.profitability.rotation import estimate_rotation_budget
from tests.contract import assert_matches_contract
from tests.fixture_data import F1, F1_ID, F2, F2_ID

SECRET = "test-secret-" + "x" * 32
PASSWORD = "correct horse 9"
SRC = MetricSource(dataset="test", provider="test")


def _poly(g) -> dict:
    return {"type": "Polygon", "coordinates": [[list(c) for c in g.exterior.coords]]}


def metric(key: str, value, unit: str = "x", category=MetricCategory.soil,
           quality=Quality.estimated) -> Metric:
    return Metric(key=key, label=key, category=category, value=value, unit=unit, quality=quality,
                  unavailable_reason="down" if value is None else None, source=SRC, resolution_m=None)


SOIL = {  # per CSB field id; None = buffered point (saved point)
    F1_ID: {"soil_productivity_nccpi": 82, "soil_organic_matter_pct": 3.5, "soil_ph": 6.4,
            "soil_texture_class": "Loam"},
    F2_ID: {"soil_productivity_nccpi": 64, "soil_organic_matter_pct": 3.5, "soil_ph": 7.6,
            "soil_texture_class": "Loam"},
    None: {"soil_productivity_nccpi": None, "soil_organic_matter_pct": 2.0, "soil_ph": 6.8,
           "soil_texture_class": "Silt loam"},
}


@pytest.fixture
def api(make_client, data_dir):
    client = make_client(data_dir, jwt_secret=SECRET, rate_limit_requests=1000)
    svc = client.app.state.services
    svc.snapshot_fails = False

    async def snapshot(sel: FieldSelection) -> Snapshot:
        if svc.snapshot_fails:
            raise RuntimeError("down")
        values = SOIL[sel.field_id]
        return Snapshot(selection=sel, generated_at=datetime.now(UTC), cached=False,
                        metrics=[metric(k, v) for k, v in values.items()])

    async def info(point: LatLon) -> FieldInfo:
        steep = point.lat > 41.9  # the saved point near Ames
        return FieldInfo(point=point, generated_at=datetime.now(UTC), cached=False, metrics=[
            metric("slope", 7.5 if steep else 1.2, "%", MetricCategory.terrain),
            metric("soil_drainage", "Poorly drained", "class"),
            metric("land_cover", "Cultivated crops", "class", MetricCategory.vegetation),
            metric("precipitation_normal", 880.0, "mm", MetricCategory.precipitation, Quality.modeled),
            metric("temperature_normal", 9.4, "degC", MetricCategory.temperature, Quality.modeled),
        ])

    svc.snapshots.snapshot = snapshot
    svc.field_info.info = info
    return client


def login(api) -> dict[str, str]:
    r = api.post("/v1/auth/register",
                 json={"email": f"farmer-{uuid.uuid4().hex[:10]}@example.com", "password": PASSWORD})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def save(api, auth, name: str, **body) -> str:
    r = api.post("/v1/me/fields", headers=auth, json={"name": name, **body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def compare(api, auth, ids, **body):
    return api.post("/v1/comparisons/saved-fields", headers=auth, json={"saved_field_ids": ids, **body})


def rows_of(r) -> dict[str, dict]:
    return {row["key"]: row for row in r.json()["rows"]}


def cell(row: dict, fid: str):
    return next(c for c in row["cells"] if c["saved_field_id"] == fid)


# ---------- saved fields ----------

def test_compare_two_csb_fields(api):
    auth = login(api)
    a = save(api, auth, "Home 40", field_id=F1_ID, geometry=_poly(F1))
    b = save(api, auth, "East 40", field_id=F2_ID, geometry=_poly(F2))

    r = compare(api, auth, [a, b], rent_per_acre={a: 200}, home={"lat": 41.60, "lon": -93.60})
    assert r.status_code == 200, r.text
    assert_matches_contract(r)
    body = r.json()
    fa, fb = body["fields"]
    assert [fa["label"], fb["label"]] == ["A", "B"]
    assert fa["name"] == "Home 40" and fa["field_id"] == F1_ID and fa["county"]["fips"] == "19153"

    # History: CSB for F1 (Corn 2025, Soybeans 2024, Corn 2023); none for F2.
    assert fa["history"]["source"] == "usda_csb" and fa["history"]["latest_crop"] == "Corn"
    assert fa["history"]["pattern"] == "corn_soybean" and fa["history"]["corn_in_a_row"] == 1
    assert fb["history"]["source"] == "none" and fb["history"]["pattern"] == "unknown"

    # Rent: the farmer's figure for A, the (placeholder) state reference for B.
    assert fa["rent"] == {"per_acre": 200.0, "source": "farmer", "is_placeholder": False}
    assert fb["rent"]["source"] == "state_baseline" and fb["rent"]["per_acre"] == 270.0

    # Money matches the rotation budget: A follows corn, so it starts with soybeans.
    budget = estimate_rotation_budget(
        [{"year": 1, "season": "main", "crop": "soybean"}, {"year": 2, "season": "main", "crop": "corn"}],
        "IA", fa["area_ha"], RotationBudgetOptions(land_rent_per_acre=200), previous_crop="Corn")
    assert fa["net_return_per_acre"]["base"] == budget.annual_average.base.profit_per_acre
    assert fa["break_even_rent_per_acre"]["base"] == pytest.approx(fa["net_return_per_acre"]["base"] + 200)
    assert fa["budget"]["years"][0]["main_crops"] == ["soybean"]
    assert fb["budget"]["years"][0]["main_crops"] == ["corn"]

    rows = rows_of(r)
    assert rows["net_return_per_acre"]["best"] == [a]  # lower rent, same state yields
    assert rows["rent"]["best"] == [a]
    assert rows["soil_productivity_nccpi"]["best"] == [a]
    assert rows["rent_per_productivity_point"]["best"] == [a]
    assert cell(rows["rent_per_productivity_point"], a)["value"] == round(200 / 82, 2)
    assert rows["soil_ph"]["best"] == [a] and rows["soil_ph"]["target"] == {"min": 6.0, "max": 7.0}
    # Same organic matter on both: no winner, flagged as not separating the fields.
    assert rows["soil_organic_matter_pct"]["best"] == [] and rows["soil_organic_matter_pct"]["same_for_all"]
    assert rows["soil_texture_class"]["same_for_all"] and rows["soil_texture_class"]["best"] == []
    assert rows["distance_from_home"]["best"] == [a]
    assert cell(rows["distance_from_home"], a)["value"] == 0.0
    assert cell(rows["corn_in_a_row"], b)["quality"] == "unavailable"
    assert body["best"] == {"net_return": [a], "soil_productivity": [a], "rent_value": [a]}

    assert any("Most productive soil" in s for s in fa["strengths"])
    assert any("placeholder" in c for c in fb["cautions"])
    assert any("placeholder" in w for w in body["warnings"])
    assert body["plan"] == {"rotation": ["corn", "soybean"], "horizon_years": 2}
    assert body["disclaimer"]


def test_compare_point_field_with_farmer_history(api):
    auth = login(api)
    a = save(api, auth, "Home 40", field_id=F1_ID, geometry=_poly(F1))
    p = save(api, auth, "Ames point", geometry={"type": "Point", "coordinates": [-93.69, 41.98]},
             crop_history=[{"year": 2025, "crop": "Corn"}, {"year": 2024, "crop": "Corn"},
                           {"year": 2023, "crop": "Corn"}])
    r = compare(api, auth, [p, a], plan={"rotation": ["corn"], "horizon_years": 3})
    assert r.status_code == 200, r.text
    assert_matches_contract(r)
    fp = r.json()["fields"][0]
    assert fp["boundary_type"] == "buffered_point" and fp["area_ha"] is None
    assert fp["history"]["source"] == "farmer" and fp["history"]["pattern"] == "continuous_corn"
    assert fp["net_return_field"] is None and fp["net_return_per_acre"] is not None
    assert any("3 years in a row" in c for c in fp["cautions"])
    assert any("Slope about 7.5%" in c for c in fp["cautions"])
    assert any("No mapped field boundary" in c for c in fp["cautions"])
    rows = rows_of(r)
    assert cell(rows["soil_productivity_nccpi"], p)["quality"] == "unavailable"
    assert rows["soil_productivity_nccpi"]["best"] == []  # only one rated field
    assert rows["slope"]["best"] == [a]
    assert "distance_from_home" not in rows


def test_compare_fetches_missing_field_context(api):
    auth = login(api)
    a = save(api, auth, "A", field_id=F1_ID, geometry=_poly(F1))
    b = save(api, auth, "B", field_id=F2_ID, geometry=_poly(F2))
    user = api.get("/v1/me", headers=auth).json()["id"]
    api.app.state.services.saved_fields.update(uuid.UUID(user), uuid.UUID(b), {"info": None,
                                                                               "info_fetched_at": None})
    r = compare(api, auth, [a, b])
    assert r.status_code == 200
    fb = r.json()["fields"][1]
    assert fb["info_as_of"] is not None  # fetched live
    assert cell(rows_of(r)["slope"], b)["value"] == 1.2
    assert api.get(f"/v1/me/fields/{b}", headers=auth).json()["info"] is None  # not stored


def test_compare_snapshot_down_still_answers(api):
    auth = login(api)
    a = save(api, auth, "A", field_id=F1_ID, geometry=_poly(F1))
    b = save(api, auth, "B", field_id=F2_ID, geometry=_poly(F2))
    api.app.state.services.snapshot_fails = True
    r = compare(api, auth, [a, b])
    assert r.status_code == 200
    assert_matches_contract(r)
    soil = rows_of(r)["soil_ph"]
    assert all(c["quality"] == "unavailable" and c["note"] for c in soil["cells"])
    assert all(any("Soil data could not be loaded" in c for c in f["cautions"]) for f in r.json()["fields"])


def test_compare_errors(api):
    alice, bob = login(api), login(api)
    a = save(api, alice, "A", field_id=F1_ID, geometry=_poly(F1))
    b = save(api, alice, "B", field_id=F2_ID, geometry=_poly(F2))
    c = save(api, bob, "Bob's", field_id=F2_ID, geometry=_poly(F2))

    r = api.post("/v1/comparisons/saved-fields", json={"saved_field_ids": [a, b]})
    assert r.status_code == 401
    assert_matches_contract(r)

    r = compare(api, alice, [a, c])  # Bob's field is invisible to Alice
    assert r.status_code == 404
    assert_matches_contract(r)
    assert r.json()["error"]["code"] == "NOT_FOUND"

    for body in (
        {"saved_field_ids": [a]},
        {"saved_field_ids": [a, a]},
        {"saved_field_ids": [a, b, *[str(uuid.uuid4()) for _ in range(3)]]},
        {"saved_field_ids": [a, "not-a-uuid"]},
        {"saved_field_ids": [a, b], "rent_per_acre": {c: 100}},
        {"saved_field_ids": [a, b], "rent_per_acre": {a: -1}},
        {"saved_field_ids": [a, b], "plan": {"rotation": ["oats"]}},
        {"saved_field_ids": [a, b], "plan": {"horizon_years": 9}},
        {"saved_field_ids": [a, b], "owner": "x"},
    ):
        r = api.post("/v1/comparisons/saved-fields", headers=alice, json=body)
        assert r.status_code == 422, body
        assert_matches_contract(r)


def test_compare_crop_override_changes_money(api):
    auth = login(api)
    a = save(api, auth, "A", field_id=F1_ID, geometry=_poly(F1))
    b = save(api, auth, "B", field_id=F2_ID, geometry=_poly(F2))
    base = compare(api, auth, [a, b], rent_per_acre={a: 250, b: 250}).json()
    override = {"crop": "corn", "revenue_per_acre": {"low": 700, "base": 900, "high": 1100},
                "production_cost_per_acre": 500}
    r = compare(api, auth, [a, b], rent_per_acre={a: 250, b: 250}, crop_overrides=[override])
    assert r.status_code == 200
    assert_matches_contract(r)
    assert r.json()["fields"][1]["net_return_per_acre"] != base["fields"][1]["net_return_per_acre"]


# ---------- rules ----------

def test_history_patterns():
    assert summarize_history([], "none").pattern == "unknown"
    assert summarize_history([(2025, "Corn")], "usda_csb").pattern == "unknown"
    s = summarize_history([(2023, "Corn"), (2025, "Corn"), (2024, "Soybeans"), (2022, "Soybeans")],
                          "usda_csb")
    assert (s.pattern, s.latest_crop, s.corn_years, s.soybean_years, s.first_year) == \
        ("corn_soybean", "Corn", 2, 2, 2022)
    s = summarize_history([(2025, "Corn"), (2024, "Corn"), (2023, "Corn"), (2022, "Soybeans")], "farmer")
    assert s.pattern == "continuous_corn" and s.corn_in_a_row == 3
    s = summarize_history([(2025, "Soybeans"), (2024, "Soybeans")], "farmer")
    assert s.pattern == "continuous_soybean"
    s = summarize_history([(2025, "Corn"), (2024, "Alfalfa"), (2023, "Oats")], "farmer")
    assert s.pattern == "mixed" and s.other_years == 2 and s.distinct_crops == 3


def test_plan_sequence_follows_last_crop():
    plan = ComparisonPlan(rotation=["corn", "soybean"], horizon_years=3)
    assert [s["crop"] for s in _sequence(plan, "Corn")] == ["soybean", "corn", "soybean"]
    assert [s["crop"] for s in _sequence(plan, "Soybeans")] == ["corn", "soybean", "corn"]
    assert [s["crop"] for s in _sequence(plan, "Oats")] == ["corn", "soybean", "corn"]
    assert [s["crop"] for s in _sequence(plan, None)] == ["corn", "soybean", "corn"]


def test_best_of_rules():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def cells(*values):
        return [ComparisonCell(saved_field_id=i, value=v,
                               quality=Quality.unavailable if v is None else Quality.estimated)
                for i, v in zip((a, b, c), values, strict=False)]

    assert best_of(cells(1, 3, 2), "higher") == [b]
    assert best_of(cells(1, 3, 1), "lower") == [a, c]
    assert best_of(cells(2, 2), "higher") == []  # all tie: nothing to point at
    assert best_of(cells(5, None), "higher") == []  # one comparable value
    assert best_of(cells(5.5, 6.5, 7.4), "target", ValueRange(min=6, max=7)) == [b]
    assert best_of(cells(6.2, 6.8, 7.4), "target", ValueRange(min=6, max=7)) == [a, b]
    assert best_of(cells("Loam", "Clay"), "none") == []


# ---------- area rankings ----------

@pytest.fixture
def area_api(api):
    svc = api.app.state.services
    store = svc.area_rankings.store
    with store._pool.connection() as c:
        c.execute("DELETE FROM field_soil")
    svc.area_rankings._cache.clear()
    svc.soil_calls = []

    async def fetch(client, points):
        svc.soil_calls.append([p[0] for p in points])
        ratings = {F1_ID: 71.5, F2_ID: 88.0}
        soil = {"mukey": "1", "soil_name": "Clarion", "drainage": "Well drained"}
        return {fid: {**soil, "nccpi": ratings.get(fid)} for fid, _, _ in points}

    svc.area_rankings.filler.fetch = fetch
    return api


def rank(api, auth, **body):
    body.setdefault("area", {"county_fips": "19153"})
    return api.post("/v1/comparisons/area", headers=auth, json=body)


def wait_complete(api, auth, **body):
    deadline = time.monotonic() + 10
    while True:
        r = rank(api, auth, **body)
        assert r.status_code == 200, r.text
        if r.json()["soil"]["status"] == "complete" or time.monotonic() > deadline:
            return r
        time.sleep(0.05)


def test_area_ranking_fills_soil_and_ranks(area_api):
    auth = login(area_api)
    r = rank(area_api, auth, sort="area")
    assert r.status_code == 200, r.text
    assert_matches_contract(r)
    first = r.json()
    assert first["soil"]["status"] == "filling" and first["soil"]["fields_total"] == 2
    assert first["area"]["kind"] == "county" and first["area"]["county"]["name"] == "Polk"
    assert first["total"] == 2

    r = wait_complete(area_api, auth)
    assert_matches_contract(r)
    body = r.json()
    assert body["soil"] == {**body["soil"], "status": "complete", "fields_rated": 2}
    assert [i["field_id"] for i in body["items"]] == [F2_ID, F1_ID]  # by productivity
    top, second = body["items"]
    assert (top["rank"], top["productivity"], top["productivity_percentile"]) == (1, 88.0, 100)
    assert (second["rank"], second["productivity_percentile"]) == (2, 0)
    assert second["history"]["latest_crop"] == "Corn" and second["history"]["pattern"] == "corn_soybean"
    assert top["soil_name"] == "Clarion" and top["drainage"] == "Well drained"
    assert body["stats"]["productivity"] == {"p25": 75.6, "median": 79.8, "p75": 83.9}
    assert body["next_offset"] is None
    calls = area_api.app.state.services.soil_calls
    assert [sorted(c) for c in calls] == [[F1_ID, F2_ID]]  # one batch, never repeated

    # Paging: one per page.
    page = rank(area_api, auth, limit=1).json()
    assert [i["field_id"] for i in page["items"]] == [F2_ID] and page["next_offset"] == 1
    page = rank(area_api, auth, limit=1, offset=1).json()
    assert [i["field_id"] for i in page["items"]] == [F1_ID] and page["next_offset"] is None


def test_area_filters_pins_and_distance(area_api):
    auth = login(area_api)
    wait_complete(area_api, auth)

    r = rank(area_api, auth, filters={"latest_crops": ["corn"]}, pinned_field_ids=[F2_ID, "csb_nope"])
    assert r.status_code == 200
    assert_matches_contract(r)
    body = r.json()
    assert body["total"] == 1 and [i["field_id"] for i in body["items"]] == [F1_ID]
    pinned = body["pinned"][0]
    assert pinned["field_id"] == F2_ID and pinned["rank"] is None and not pinned["matches_filters"]
    assert any("csb_nope" in n for n in body["notes"])

    assert rank(area_api, auth, filters={"min_productivity": 80}).json()["total"] == 1
    assert rank(area_api, auth, filters={"min_area_ha": 1000}).json()["total"] == 0
    # F1 has corn only once in a row: not excluded.
    assert rank(area_api, auth, filters={"exclude_continuous_corn": True}).json()["total"] == 2

    r = rank(area_api, auth, sort="distance", near={"lat": 41.60, "lon": -93.60})
    items = r.json()["items"]
    assert [i["field_id"] for i in items] == [F1_ID, F2_ID]
    assert items[0]["distance_km"] < 0.1 < items[1]["distance_km"]

    # A box or a township outline around F1 only.
    w, s, e, n = F1.buffer(0.001).bounds
    r = rank(area_api, auth, area={"bbox": [w, s, e, n]})
    assert r.status_code == 200 and [i["field_id"] for i in r.json()["items"]] == [F1_ID]
    assert r.json()["area"]["kind"] == "bbox"
    r = rank(area_api, auth, area={"polygon": _poly(F1.buffer(0.001, join_style="mitre"))})
    assert r.status_code == 200
    assert_matches_contract(r)
    assert [i["field_id"] for i in r.json()["items"]] == [F1_ID]


def test_area_soil_lookup_failure_is_reported(area_api):
    svc = area_api.app.state.services

    async def broken(client, points):
        raise httpx.ConnectError("SDA down")

    svc.area_rankings.filler.fetch = broken
    auth = login(area_api)
    assert rank(area_api, auth).json()["soil"]["status"] == "filling"
    deadline = time.monotonic() + 5
    while svc.area_rankings.filler.filling("county:19153") and time.monotonic() < deadline:
        time.sleep(0.02)
    r = rank(area_api, auth)
    assert r.status_code == 200
    assert_matches_contract(r)
    body = r.json()
    assert body["soil"]["status"] == "unavailable" and body["soil"]["fields_rated"] == 0
    assert all(i["productivity"] is None for i in body["items"]) and body["total"] == 2


def test_area_errors(area_api, make_client, data_dir):
    auth = login(area_api)
    r = area_api.post("/v1/comparisons/area", json={"area": {"county_fips": "19153"}})
    assert r.status_code == 401
    assert_matches_contract(r)
    for body, status, code in (
        ({"area": {"county_fips": "48453"}}, 422, "OUTSIDE_COVERAGE"),
        ({"area": {"county_fips": "19999"}}, 404, "NOT_FOUND"),
        ({"area": {"bbox": [-95, 41, -93, 43]}}, 422, "VALIDATION_ERROR"),
        ({"area": {"bbox": [-93, 41, -94, 42]}}, 422, "VALIDATION_ERROR"),
        ({"area": {"county_fips": "19153"}, "sort": "distance"}, 422, "VALIDATION_ERROR"),
        ({"area": {"county_fips": "19153"}, "limit": 500}, 422, "VALIDATION_ERROR"),
        ({"area": {"county_fips": "19153"}, "filters": {"min_area_ha": 5, "max_area_ha": 1}}, 422,
         "VALIDATION_ERROR"),
        ({"area": {"polygon": {"type": "Polygon",
                               "coordinates": [[[-93.7, 41.6], [-93.6, 41.6], [-93.6, 41.7]]]}}},
         422, "VALIDATION_ERROR"),
        ({"area": {"state": "IA"}}, 422, "VALIDATION_ERROR"),
    ):
        r = area_api.post("/v1/comparisons/area", headers=auth, json=body)
        assert r.status_code == status, (body, r.text)
        assert_matches_contract(r)
        assert r.json()["error"]["code"] == code

    small = make_client(data_dir, jwt_secret=SECRET, area_max_fields=1, area_soil_fill=False)
    r = rank(small, login(small))
    assert r.status_code == 422
    assert r.json()["error"]["details"] == {"max_fields": 1}


# ---------- Soil Data Access batch ----------

@respx.mock
async def test_fetch_point_soils_maps_points_to_ratings():
    route = respx.post(soil_batch.URL).mock(side_effect=[
        httpx.Response(200, json={"Table": [["id", "mukey"], ["0", "412898"], ["1", "drop table"],
                                            ["0", "999"]]}),
        httpx.Response(200, json={"Table": [["mukey", "nccpi", "soil_name", "drainage"],
                                            ["412898", "0.926", "Terril", "Moderately well drained"]]}),
    ])
    async with httpx.AsyncClient() as c:
        out = await soil_batch.fetch_point_soils(c, [("f1", -93.6, 41.6), ("f2", -93.5, 41.6)])
    assert out == {
        "f1": {"mukey": "412898", "nccpi": 92.6, "soil_name": "Terril",
               "drainage": "Moderately well drained"},
        "f2": {"mukey": None, "nccpi": None, "soil_name": None, "drainage": None},
    }
    first, second = (call.request.content.decode() for call in route.calls)
    assert "(0,'point(-93.600000 41.600000)')" in first
    assert "'412898'" in second and "drop table" not in second
