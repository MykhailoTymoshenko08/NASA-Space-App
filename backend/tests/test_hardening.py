"""M6: rate limits, error envelope edge cases, unit tests for small helpers."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import pytest
import respx
from fastapi import Request

from app.auth.tokens import create_access_token
from app.core import ratelimit
from app.core.db import open_pool
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


def test_rate_limiter_expires_keys_without_resetting_quotas_at_capacity():
    rl = RateLimiter(limit=1, window_s=10, max_keys=2)
    rl.check("a", now=0)
    rl.check("b", now=1)
    with pytest.raises(ApiException) as error:
        rl.check("c", now=2)
    assert error.value.headers["Retry-After"] == "8"
    with pytest.raises(ApiException):
        rl.check("a", now=2)  # no eviction of a live client's quota
    rl.check("c", now=10)
    assert set(rl._hits) == {"b", "c"}
    rl.check("d", now=20)
    assert set(rl._hits) == {"d"}


def _quota_request(app, token=None):
    return Request({
        "type": "http", "app": app, "client": ("203.0.113.7", 1234),
        "headers": [(b"authorization", f"Bearer {token}".encode())] if token is not None else [],
    })


def test_signed_in_users_share_ip_but_not_authenticated_quota():
    secret = "quota-test-" + "x" * 32
    users = {key: SimpleNamespace(id=key, auth_version=0) for key in (uuid.uuid4(), uuid.uuid4())}
    app = SimpleNamespace(state=SimpleNamespace(
        services=SimpleNamespace(jwt_secret=secret, users=SimpleNamespace(get_by_id=users.get)),
        limiters={"comparisons": RateLimiter(1, 60)},
    ))
    tokens = [create_access_token(key, secret, timedelta(minutes=1)) for key in users]
    check = ratelimit.rate_limited("comparisons")
    check(_quota_request(app, tokens[0]))
    check(_quota_request(app, tokens[1]))
    with pytest.raises(ApiException):
        check(_quota_request(app, tokens[0]))


@pytest.mark.parametrize("bucket", ["auth", "password"])
def test_authentication_quota_stays_per_ip_even_with_valid_tokens(bucket):
    secret = "quota-test-" + "x" * 32
    users = {key: SimpleNamespace(id=key, auth_version=0) for key in (uuid.uuid4(), uuid.uuid4())}
    app = SimpleNamespace(state=SimpleNamespace(
        services=SimpleNamespace(jwt_secret=secret, users=SimpleNamespace(get_by_id=users.get)),
        limiters={bucket: RateLimiter(1, 60)},
    ))
    tokens = [create_access_token(key, secret, timedelta(minutes=1)) for key in users]
    check = ratelimit.rate_limited(bucket)
    check(_quota_request(app, tokens[0]))
    with pytest.raises(ApiException):
        check(_quota_request(app, tokens[1]))


@pytest.mark.parametrize("credential", ["malformed", "expired", "revoked", "unknown"])
def test_unverified_credentials_cannot_escape_ip_quota(credential):
    secret = "quota-test-" + "x" * 32
    user_id = uuid.uuid4()
    current = SimpleNamespace(id=user_id, auth_version=1 if credential == "revoked" else 0)
    app = SimpleNamespace(state=SimpleNamespace(
        services=SimpleNamespace(jwt_secret=secret, users=SimpleNamespace(
            get_by_id=lambda key: None if credential == "unknown" else current)),
        limiters={"analyses": RateLimiter(1, 60)},
    ))
    token = "invalid" if credential == "malformed" else create_access_token(
        user_id, secret, timedelta(minutes=-1 if credential == "expired" else 1))
    check = ratelimit.rate_limited("analyses")
    check(_quota_request(app, token))
    with pytest.raises(ApiException):
        check(_quota_request(app))


def test_missing_services_uses_ip_quota():
    app = SimpleNamespace(state=SimpleNamespace(limiters={"analyses": RateLimiter(1, 60)}))
    check = ratelimit.rate_limited("analyses")
    check(_quota_request(app, "invalid"))
    with pytest.raises(ApiException):
        check(_quota_request(app))


def test_postgres_limiter_instances_share_atomic_quota(db_url):
    pool = open_pool(db_url, max_size=4)
    pool.open(wait=True, timeout=5)
    try:
        bucket = "test-" + uuid.uuid4().hex
        first = ratelimit.PostgreSQLRateLimiter(pool, bucket, limit=2, window_s=10)
        second = ratelimit.PostgreSQLRateLimiter(pool, bucket, limit=2, window_s=10)

        def hit(index):
            try:
                (first if index % 2 else second).check("a", now=1000)
                return "accepted"
            except ApiException as error:
                assert error.code == "RATE_LIMITED" and error.headers["Retry-After"] == "10"
                return "limited"

        with ThreadPoolExecutor(max_workers=4) as threads:
            results = list(threads.map(hit, range(12)))
        assert results.count("accepted") == 2 and results.count("limited") == 10
        second.check("b", now=1001)  # independent key, same bucket
        first.check("a", now=1010)  # expired hits no longer count
    finally:
        pool.close()


def test_postgres_limiter_bounds_keys_and_frees_expired_capacity(db_url):
    pool = open_pool(db_url, max_size=2)
    pool.open(wait=True, timeout=5)
    try:
        bucket = "test-" + uuid.uuid4().hex
        first = ratelimit.PostgreSQLRateLimiter(pool, bucket, limit=1, window_s=10, max_keys=1)
        second = ratelimit.PostgreSQLRateLimiter(pool, bucket, limit=1, window_s=10, max_keys=1)
        first.check("a", now=1000)
        with pytest.raises(ApiException) as error:
            second.check("b", now=1001)
        assert error.value.headers["Retry-After"] == "9"
        with pytest.raises(ApiException):
            first.check("a", now=1002)
        second.check("b", now=1010)
        with pool.connection() as connection:
            rows = connection.execute(
                "SELECT client_key FROM request_limits WHERE bucket = %s", (bucket,)
            ).fetchall()
        assert [row["client_key"] for row in rows] == ["b"]
    finally:
        pool.close()


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

    def boom(svc, url):
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
