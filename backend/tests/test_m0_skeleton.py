import pytest

from tests.contract import assert_matches_contract


def test_health_matches_contract(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert_matches_contract(r)


def test_request_id_generated_and_echoed(client):
    r = client.get("/v1/health")
    assert len(r.headers["x-request-id"]) >= 16
    r = client.get("/v1/health", headers={"X-Request-Id": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"


def test_unsafe_request_id_is_replaced(client):
    r = client.get("/v1/health", headers={"X-Request-Id": "x" * 500})
    assert r.headers["x-request-id"] != "x" * 500


def test_unknown_route_uses_error_envelope(client):
    r = client.get("/v1/nope")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["request_id"] == r.headers["x-request-id"]


def test_cors_allows_frontend_origin(client):
    r = client.options(
        "/v1/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert r.headers.get("x-request-id")


@pytest.mark.parametrize("origin", ["http://evil.example"])
def test_cors_rejects_other_origins(client, origin):
    r = client.get("/v1/health", headers={"Origin": origin})
    assert "access-control-allow-origin" not in r.headers


def test_cors_extra_origins(make_client, data_dir):
    c = make_client(data_dir, database_url="", frontend_origin="https://app.example",
                    cors_extra_origins=" http://localhost:5173/ , https://preview.example")
    for origin in ("https://app.example", "http://localhost:5173", "https://preview.example"):
        r = c.get("/v1/health", headers={"Origin": origin})
        assert r.headers["access-control-allow-origin"] == origin
    r = c.get("/v1/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
