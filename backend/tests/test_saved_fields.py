"""Saved fields: CRUD under /v1/me/fields, ownership (404 for others), validation, per-user cap.

The /fields/info service is replaced with a fake, so these tests make no network calls.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.models import FieldInfo, LatLon, Metric, MetricCategory, MetricSource, Quality
from tests.contract import assert_matches_contract

SECRET = "test-secret-" + "x" * 32
PASSWORD = "correct horse 9"

# ~0.8 x 1.1 km square near Ames, IA: about 90 ha.
SQUARE = [[-93.70, 41.98], [-93.69, 41.98], [-93.69, 41.99], [-93.70, 41.99], [-93.70, 41.98]]
POLYGON = {"type": "Polygon", "coordinates": [SQUARE]}


def fake_info(point: LatLon, quality: Quality = Quality.measured) -> FieldInfo:
    return FieldInfo(
        point=point,
        generated_at=datetime.now(UTC),
        cached=False,
        metrics=[Metric(
            key="elevation", label="Elevation", category=MetricCategory.terrain,
            value=None if quality == Quality.unavailable else 290.0, unit="m", quality=quality,
            unavailable_reason="down" if quality == Quality.unavailable else None,
            source=MetricSource(dataset="3DEP", provider="USGS"), resolution_m=10,
        )],
    )


@pytest.fixture
def api(make_client, data_dir):
    client = make_client(data_dir, jwt_secret=SECRET, saved_fields_max_per_user=3)
    svc = client.app.state.services
    svc.fake_info_quality = Quality.measured

    async def info(point: LatLon) -> FieldInfo:
        return fake_info(point, svc.fake_info_quality)

    svc.field_info.info = info
    return client


def login(api) -> dict[str, str]:
    email = f"farmer-{uuid.uuid4().hex[:10]}@example.com"
    r = api.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def create(api, auth, **body):
    return api.post("/v1/me/fields", headers=auth, json={"name": "North 80", "geometry": POLYGON, **body})


def test_create_get_list_polygon(api):
    auth = login(api)
    r = create(api, auth, name="  North 80 ", field_id="csb2025_1",
               crop_history=[{"year": 2025, "crop": "Corn"}, {"year": 2024, "crop": "Soybeans"}])
    assert r.status_code == 201, r.text
    assert_matches_contract(r)
    f = r.json()
    assert r.headers["location"] == f"/v1/me/fields/{f['id']}"
    assert f["name"] == "North 80"
    assert f["state"] == "IA"
    assert f["field_id"] == "csb2025_1"
    assert f["geometry"] == POLYGON
    assert 80 < f["area_ha"] < 100
    assert -93.70 < f["centroid"]["lon"] < -93.69 and 41.98 < f["centroid"]["lat"] < 41.99
    assert f["crop_history"][0] == {"year": 2025, "crop": "Corn"}
    assert f["info"]["metrics"][0]["value"] == 290.0
    assert f["info_fetched_at"] is not None

    got = api.get(f"/v1/me/fields/{f['id']}", headers=auth)
    assert got.status_code == 200
    assert_matches_contract(got)
    assert got.json() == f

    lst = api.get("/v1/me/fields", headers=auth)
    assert lst.status_code == 200
    assert_matches_contract(lst)
    assert [i["id"] for i in lst.json()["items"]] == [f["id"]]
    assert lst.json()["limit"] == 3


def test_create_point_without_info(api):
    api.app.state.services.fake_info_quality = Quality.unavailable
    auth = login(api)
    r = create(api, auth, geometry={"type": "Point", "coordinates": [-96.7, 40.8]})  # Lincoln, NE
    assert r.status_code == 201, r.text
    assert_matches_contract(r)
    f = r.json()
    assert f["state"] == "NE" and f["area_ha"] is None and f["crop_history"] is None
    assert f["info"] is None and f["info_fetched_at"] is None

    # Upstreams still down: 502, snapshot unchanged.
    r = api.post(f"/v1/me/fields/{f['id']}/refresh-info", headers=auth)
    assert r.status_code == 502
    assert_matches_contract(r)

    api.app.state.services.fake_info_quality = Quality.measured
    r = api.post(f"/v1/me/fields/{f['id']}/refresh-info", headers=auth)
    assert r.status_code == 200
    assert_matches_contract(r)
    assert r.json()["info"]["metrics"][0]["value"] == 290.0


def test_update(api):
    auth = login(api)
    f = create(api, auth, crop_history=[{"year": 2025, "crop": "Corn"}]).json()

    r = api.patch(f"/v1/me/fields/{f['id']}", headers=auth, json={"name": "Home quarter"})
    assert r.status_code == 200, r.text
    assert_matches_contract(r)
    assert r.json()["name"] == "Home quarter"
    assert r.json()["crop_history"] == f["crop_history"]  # omitted: unchanged
    assert r.json()["updated_at"] > f["updated_at"]

    r = api.patch(f"/v1/me/fields/{f['id']}", headers=auth, json={"crop_history": None})
    assert r.status_code == 200 and r.json()["crop_history"] is None

    for body in ({}, {"name": None}, {"name": "   "}, {"name": "x" * 101}, {"geometry": POLYGON}):
        r = api.patch(f"/v1/me/fields/{f['id']}", headers=auth, json=body)
        assert r.status_code == 422, body
        assert_matches_contract(r)


def test_delete(api):
    auth = login(api)
    keep = create(api, auth, name="Keep").json()
    gone = create(api, auth, name="Gone").json()

    r = api.delete(f"/v1/me/fields/{gone['id']}", headers=auth)
    assert r.status_code == 204
    assert_matches_contract(r)
    assert api.get(f"/v1/me/fields/{gone['id']}", headers=auth).status_code == 404
    assert api.delete(f"/v1/me/fields/{gone['id']}", headers=auth).status_code == 404
    assert [i["id"] for i in api.get("/v1/me/fields", headers=auth).json()["items"]] == [keep["id"]]


def test_other_users_fields_are_404(api):
    alice, bob = login(api), login(api)
    a = create(api, alice, name="Alice's").json()
    b = create(api, bob, name="Bob's").json()

    assert [i["id"] for i in api.get("/v1/me/fields", headers=bob).json()["items"]] == [b["id"]]
    for method, path, body in (
        ("GET", f"/v1/me/fields/{a['id']}", None),
        ("PATCH", f"/v1/me/fields/{a['id']}", {"name": "mine now"}),
        ("DELETE", f"/v1/me/fields/{a['id']}", None),
        ("POST", f"/v1/me/fields/{a['id']}/refresh-info", None),
        ("GET", "/v1/me/fields/not-a-uuid", None),
    ):
        r = api.request(method, path, headers=bob, json=body)
        assert r.status_code == 404, (method, path)
        assert_matches_contract(r)
        assert r.json()["error"]["code"] == "NOT_FOUND"

    # Bob deleting his own field leaves Alice's untouched.
    assert api.delete(f"/v1/me/fields/{b['id']}", headers=bob).status_code == 204
    r = api.get(f"/v1/me/fields/{a['id']}", headers=alice)
    assert r.status_code == 200 and r.json()["name"] == "Alice's"


def test_requires_auth(api):
    r = api.get("/v1/me/fields")
    assert r.status_code == 401
    assert_matches_contract(r)
    assert create(api, {}).status_code == 401


def ring(*pts):
    return {"type": "Polygon", "coordinates": [list(map(list, pts))]}


@pytest.mark.parametrize("body,code", [
    ({"name": ""}, "VALIDATION_ERROR"),
    ({"name": "x" * 101}, "VALIDATION_ERROR"),
    ({"geometry": {"type": "Point", "coordinates": [-97.74, 30.27]}}, "OUTSIDE_COVERAGE"),  # Austin, TX
    ({"geometry": ring([-93.7, 41.98], [-93.69, 41.98], [-93.69, 41.99], [-93.7, 41.99])},
     "VALIDATION_ERROR"),  # not closed
    ({"geometry": ring([-93.7, 41.98], [-93.69, 41.98], [-93.7, 41.98])}, "VALIDATION_ERROR"),
    ({"geometry": ring([-93.7, 41.98], [-93.69, 41.99], [-93.69, 41.98], [-93.7, 41.99], [-93.7, 41.98])},
     "VALIDATION_ERROR"),  # bow tie
    ({"geometry": ring([-94.5, 41.5], [-93.5, 41.5], [-93.5, 42.5], [-94.5, 42.5], [-94.5, 41.5])},
     "VALIDATION_ERROR"),  # ~9,000 km2
    ({"geometry": {"type": "Polygon", "coordinates": [[[-93.7, 41.98, 1], [-93.69, 41.98, 1],
                                                       [-93.69, 41.99, 1], [-93.7, 41.98, 1]]]}},
     "VALIDATION_ERROR"),
    ({"geometry": {"type": "LineString", "coordinates": [[-93.7, 41.98], [-93.69, 41.98]]}},
     "VALIDATION_ERROR"),
    ({"crop_history": [{"year": 2025, "crop": "Corn"}] * 11}, "VALIDATION_ERROR"),
    ({"owner": "someone-else"}, "VALIDATION_ERROR"),
])
def test_create_validation(api, body, code):
    r = create(api, login(api), **body)
    assert r.status_code == 422, r.text
    assert_matches_contract(r)
    assert r.json()["error"]["code"] == code


def test_limit_per_user(api):
    auth, other = login(api), login(api)
    for i in range(3):
        assert create(api, auth, name=f"F{i}").status_code == 201
    r = create(api, auth, name="one too many")
    assert r.status_code == 409
    assert_matches_contract(r)
    assert r.json()["error"]["code"] == "FIELD_LIMIT_REACHED"
    assert r.json()["error"]["details"] == {"limit": 3}
    assert create(api, other).status_code == 201  # the cap is per user
