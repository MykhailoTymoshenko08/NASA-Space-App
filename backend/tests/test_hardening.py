"""M6: rate limits, error envelope edge cases, unit tests for small helpers."""

import pytest
import respx

from app.core.errors import ApiException
from app.core.ratelimit import RateLimiter
from tests.contract import assert_matches_contract
from tests.test_snapshots import mock_all

pytestmark = pytest.mark.contract


def test_rate_limiter_window():
    rl = RateLimiter(limit=2, window_s=10)
    rl.check("a", now=0)
    rl.check("a", now=1)
    with pytest.raises(ApiException) as ei:
        rl.check("a", now=2)
    assert ei.value.code == "RATE_LIMITED"
    assert ei.value.headers["Retry-After"] == "8"
    rl.check("b", now=2)  # other client unaffected
    rl.check("a", now=10.5)  # first hit expired


def test_locations_rate_limited(make_client, data_dir):
    c = make_client(data_dir, rate_limit_requests=2)
    for _ in range(2):
        assert c.post("/v1/locations/resolve", json={"input": "41.70, -93.70"}).status_code == 200
    r = c.post("/v1/locations/resolve", json={"input": "41.70, -93.70"})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    assert r.json()["error"]["code"] == "RATE_LIMITED"
    assert_matches_contract(r)


def test_analyses_rate_limited(make_client, data_dir):
    c = make_client(data_dir, rate_limit_requests=1)
    with respx.mock(assert_all_called=False) as router:
        mock_all(router)
        body = {"selection": {"field_id": "csb2025_190000000001"}}
        assert c.post("/v1/analyses", json=body).status_code == 202
        r = c.post("/v1/analyses", json=body)
    assert r.status_code == 429
    assert r.headers["retry-after"]
    assert_matches_contract(r)


def test_other_endpoints_not_rate_limited(make_client, data_dir):
    c = make_client(data_dir, rate_limit_requests=1)
    for _ in range(3):
        assert c.get("/v1/geo/states").status_code == 200


def test_malformed_json_is_validation_error(client):
    r = client.post(
        "/v1/fields/resolve", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert_matches_contract(r)


def test_unhandled_exception_is_internal_error(client, monkeypatch):
    from app.geo import coverage

    def boom(svc):
        raise RuntimeError("secret detail")

    monkeypatch.setattr("app.api.meta.build_coverage", boom)
    from fastapi.testclient import TestClient

    c = TestClient(client.app, base_url=str(client.base_url), raise_server_exceptions=False)
    r = c.get("/v1/meta/coverage")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in body["error"]["message"]
    assert r.headers.get("x-request-id") == body["error"]["request_id"]
    assert coverage  # imported module still intact
