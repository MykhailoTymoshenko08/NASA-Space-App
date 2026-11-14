"""Auth: register, login, refresh (rotation), logout, `get_current_user` 401s, CORS with credentials.

Users persist across tests (one scratch DB per session), so every test uses its own email.
"""

import uuid
from datetime import timedelta

import pytest

from app.auth.tokens import create_access_token
from tests.contract import assert_matches_contract

SECRET = "test-secret-" + "x" * 32
PASSWORD = "correct horse 9"


@pytest.fixture
def api(make_client, data_dir):
    return make_client(data_dir, jwt_secret=SECRET)


def new_email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


def register(api, email=None, password=PASSWORD):
    return api.post("/v1/auth/register", json={"email": email or new_email(), "password": password})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_register_signs_in_and_sets_refresh_cookie(api):
    r = register(api, email="  Mixed.Case@Example.COM ")
    assert r.status_code == 201, r.text
    assert_matches_contract(r)
    body = r.json()
    assert body["user"]["email"] == "mixed.case@example.com"
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60

    cookie = r.headers["set-cookie"]
    assert cookie.startswith("refresh_token=")
    assert "HttpOnly" in cookie and "Path=/v1/auth" in cookie and "SameSite=lax" in cookie

    me = api.get("/v1/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert_matches_contract(me)
    assert me.json() == body["user"]


def test_register_duplicate_email_is_case_insensitive(api):
    email = new_email()
    assert register(api, email=email).status_code == 201
    r = register(api, email=email.upper())
    assert r.status_code == 409
    assert_matches_contract(r)
    assert r.json()["error"]["code"] == "EMAIL_TAKEN"


@pytest.mark.parametrize("email,password", [
    ("not-an-email", PASSWORD),
    (None, "short1"),
    (None, "lettersonly"),
    (None, "1234567890"),
])
def test_register_validation(api, email, password):
    r = register(api, email=email, password=password)
    assert r.status_code == 422
    assert_matches_contract(r)
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_login(api):
    email = new_email()
    register(api, email=email)

    r = api.post("/v1/auth/login", json={"email": email.upper(), "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert_matches_contract(r)
    assert api.get("/v1/me", headers=bearer(r.json()["access_token"])).json()["email"] == email


@pytest.mark.parametrize("which", ["wrong_password", "unknown_email"])
def test_login_bad_credentials_same_401(api, which):
    email = new_email()
    register(api, email=email)
    creds = {"email": email, "password": "wrong password 1"} if which == "wrong_password" else {
        "email": new_email(), "password": PASSWORD}
    r = api.post("/v1/auth/login", json=creds)
    assert r.status_code == 401
    assert_matches_contract(r)
    err = r.json()["error"]
    assert err["code"] == "UNAUTHORIZED" and err["details"]["reason"] == "invalid_credentials"


def test_protected_route_401s(api):
    user_id = register(api).json()["user"]["id"]
    expired = create_access_token(uuid.UUID(user_id), SECRET, timedelta(seconds=-10))
    other_secret = create_access_token(uuid.UUID(user_id), "y" * 40, timedelta(minutes=5))
    unknown_user = create_access_token(uuid.uuid4(), SECRET, timedelta(minutes=5))

    cases = [
        ({}, "missing_token"),
        (bearer("not-a-jwt"), "invalid_token"),
        (bearer(other_secret), "invalid_token"),
        (bearer(expired), "token_expired"),
        (bearer(unknown_user), "unknown_user"),
        ({"Authorization": "Basic Zm9vOmJhcg=="}, "missing_token"),
    ]
    for headers, reason in cases:
        r = api.get("/v1/me", headers=headers)
        assert r.status_code == 401, (reason, r.text)
        assert_matches_contract(r)
        assert r.headers["www-authenticate"] == "Bearer"
        assert r.json()["error"]["details"]["reason"] == reason


def test_refresh_rotates_and_old_token_is_single_use(api):
    reg = register(api)
    old = api.cookies.get("refresh_token")
    assert old

    r = api.post("/v1/auth/refresh")
    assert r.status_code == 200, r.text
    assert_matches_contract(r)
    new = api.cookies.get("refresh_token")
    assert new and new != old
    assert api.get("/v1/me", headers=bearer(r.json()["access_token"])).json() == reg.json()["user"]

    # Replaying the rotated-out token fails.
    api.cookies.clear()
    api.cookies.set("refresh_token", old)
    r = api.post("/v1/auth/refresh")
    assert r.status_code == 401
    assert_matches_contract(r)
    assert r.json()["error"]["details"]["reason"] == "invalid_refresh_token"


def test_refresh_without_cookie(api):
    r = api.post("/v1/auth/refresh")
    assert r.status_code == 401
    assert r.json()["error"]["details"]["reason"] == "missing_refresh_token"


def test_logout_revokes_refresh_token(api):
    register(api)
    token = api.cookies.get("refresh_token")

    r = api.post("/v1/auth/logout")
    assert r.status_code == 204
    assert_matches_contract(r)
    assert "refresh_token=" in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]

    api.cookies.set("refresh_token", token)
    assert api.post("/v1/auth/refresh").status_code == 401
    # Idempotent.
    api.cookies.clear()
    assert api.post("/v1/auth/logout").status_code == 204


def test_cors_allows_credentials_for_frontend_origin(api):
    origin = api.app.state.settings.frontend_origin
    r = api.options("/v1/auth/refresh", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin
    assert r.headers["access-control-allow-credentials"] == "true"


def test_short_jwt_secret_rejected(make_client, data_dir):
    with pytest.raises(ValueError, match="JWT_SECRET"):
        make_client(data_dir, jwt_secret="too-short")
