"""Password updates, token lifecycle, session revocation and Brevo SMTP without external mail."""

import smtplib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from app.auth.mail import PasswordResetMailer
from app.auth.store import SCHEMA_SQL, token_digest
from app.auth.tokens import hash_password, verify_password
from app.core.config import Settings
from tests.contract import assert_matches_contract

PASSWORD = "original password 1"
NEW_PASSWORD = "replacement password 2"
SECRET = "password-test-secret-" + "x" * 32


@pytest.fixture
def api(make_client, data_dir, monkeypatch):
    client = make_client(data_dir, jwt_secret=SECRET, smtp_username="smtp-login",
                         smtp_password="smtp-key", smtp_from_email="sender@example.com")
    client.mail = []
    monkeypatch.setattr(client.app.state.services.password_reset_mailer, "send_reset",
                        lambda email, token: client.mail.append((email, token)))
    return client


def register(api):
    email = f"reset-{uuid.uuid4().hex}@example.com"
    r = api.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return email, r.json(), api.cookies.get("refresh_token")


def bearer(body):
    return {"Authorization": f"Bearer {body['access_token']}"}


def forgot(api, email):
    r = api.post("/v1/auth/forgot-password", json={"email": email})
    assert r.status_code == 202, r.text
    assert r.content == b""
    assert_matches_contract(r)
    return r


def reset(api, token, password=NEW_PASSWORD):
    r = api.post("/v1/auth/reset-password", json={"token": token, "new_password": password})
    assert_matches_contract(r)
    return r


def login(api, email, password):
    return api.post("/v1/auth/login", json={"email": email, "password": password})


@pytest.mark.contract
def test_change_password_revokes_all_sessions_and_links(api):
    email, first, _ = register(api)
    second = login(api, email, PASSWORD).json()
    old_cookie = api.cookies.get("refresh_token")
    forgot(api, email)
    reset_token = api.mail[0][1]
    r = api.post("/v1/auth/change-password", headers=bearer(first), json={
        "current_password": PASSWORD, "new_password": NEW_PASSWORD,
    })
    assert r.status_code == 204, r.text
    assert_matches_contract(r)
    assert "Max-Age=0" in r.headers["set-cookie"]
    assert not api.cookies.get("refresh_token")
    for body in (first, second):
        stale = api.get("/v1/me", headers=bearer(body))
        assert stale.status_code == 401
        assert stale.json()["error"]["details"]["reason"] == "session_revoked"
    api.cookies.set("refresh_token", old_cookie)
    assert api.post("/v1/auth/refresh").status_code == 401
    assert reset(api, reset_token).status_code == 422
    assert login(api, email, PASSWORD).status_code == 401
    fresh = login(api, email, NEW_PASSWORD)
    assert fresh.status_code == 200
    assert api.get("/v1/me", headers=bearer(fresh.json())).status_code == 200


@pytest.mark.contract
def test_change_requires_auth_and_correct_current_password(api):
    email, body, _ = register(api)
    payload = {"current_password": "wrong1", "new_password": NEW_PASSWORD}
    for headers in ({}, bearer(body)):
        r = api.post("/v1/auth/change-password", headers=headers, json=payload)
        assert r.status_code == 401
        assert_matches_contract(r)
    assert login(api, email, PASSWORD).status_code == 200
    assert api.get("/v1/me", headers=bearer(body)).status_code == 200


@pytest.mark.contract
def test_forgot_normalizes_email_hides_existence_and_throttles_delivery(api):
    email, _, _ = register(api)
    existing = forgot(api, f"  {email.upper()} ")
    unknown = forgot(api, "unknown@example.com")
    again = forgot(api, email)
    assert existing.status_code == unknown.status_code == again.status_code
    assert existing.content == unknown.content == again.content
    assert len(api.mail) == 1
    assert api.mail[0][0] == email
    token = api.mail[0][1]
    with api.app.state.services.users.pool.connection() as c:
        row = c.execute("SELECT * FROM password_reset_tokens WHERE token_hash = %s",
                        (token_digest(token),)).fetchone()
    assert row["token_hash"] != token
    assert timedelta(minutes=59) < row["expires_at"] - datetime.now(UTC) <= timedelta(hours=1)


@pytest.mark.contract
def test_reset_single_use_and_session_revocation(api):
    email, body, cookie = register(api)
    forgot(api, email)
    token = api.mail[0][1]
    r = reset(api, token)
    assert r.status_code == 204
    assert "Max-Age=0" in r.headers["set-cookie"]
    assert reset(api, token).status_code == 422
    assert api.get("/v1/me", headers=bearer(body)).status_code == 401
    api.cookies.set("refresh_token", cookie)
    assert api.post("/v1/auth/refresh").status_code == 401
    assert login(api, email, PASSWORD).status_code == 401
    assert login(api, email, NEW_PASSWORD).status_code == 200


def test_expired_and_invalid_tokens_do_not_change_password(api):
    email, _, _ = register(api)
    forgot(api, email)
    token = api.mail[0][1]
    with api.app.state.services.users.pool.connection() as c:
        c.execute("UPDATE password_reset_tokens SET expires_at = now() - interval '1 second'"
                  " WHERE token_hash = %s", (token_digest(token),))
    for invalid in (token, "invalid-token"):
        r = reset(api, invalid)
        assert r.status_code == 422
        assert r.json()["error"]["details"]["field"] == "token"
    assert login(api, email, PASSWORD).status_code == 200


def test_new_request_supersedes_previous_link(api):
    email, _, _ = register(api)
    forgot(api, email)
    old = api.mail[0][1]
    with api.app.state.services.users.pool.connection() as c:
        c.execute("UPDATE password_reset_tokens SET requested_at = now() - interval '61 seconds'"
                  " WHERE token_hash = %s", (token_digest(old),))
    forgot(api, email)
    new = api.mail[-1][1]
    assert old != new
    assert reset(api, old).status_code == 422
    assert reset(api, new).status_code == 204


@pytest.mark.parametrize("password", ["short1", "onlyletters", "123456789", "a1" * 65])
@pytest.mark.parametrize("path", ["change-password", "reset-password"])
@pytest.mark.contract
def test_password_rules_match_registration(api, password, path):
    _, body, _ = register(api)
    payload = {"current_password": PASSWORD} if path == "change-password" else {"token": "test-token"}
    r = api.post(f"/v1/auth/{path}", headers=bearer(body), json={**payload, "new_password": password})
    assert r.status_code == 422
    assert_matches_contract(r)


def test_weak_password_does_not_consume_link(api):
    email, _, _ = register(api)
    forgot(api, email)
    token = api.mail[0][1]
    assert reset(api, token, "weak").status_code == 422
    assert reset(api, token).status_code == 204


@pytest.mark.contract
def test_smtp_unconfigured_for_every_email(make_client, data_dir):
    api = make_client(data_dir)
    for email in ("unknown@example.com", register(api)[0]):
        r = api.post("/v1/auth/forgot-password", json={"email": email})
        assert r.status_code == 502
        assert_matches_contract(r)


def test_send_failure_is_generic_and_can_retry(api, monkeypatch, caplog):
    email, _, _ = register(api)
    captured = []

    def fail(email, token):
        captured.append(token)
        raise smtplib.SMTPAuthenticationError(535, f"secret {token} smtp-key {email}".encode())

    monkeypatch.setattr(api.app.state.services.password_reset_mailer, "send_reset", fail)
    forgot(api, email)
    assert "SMTPAuthenticationError" in caplog.text
    assert captured[0] not in caplog.text and "smtp-key" not in caplog.text and email not in caplog.text
    monkeypatch.setattr(api.app.state.services.password_reset_mailer, "send_reset",
                        lambda email, token: api.mail.append((email, token)))
    forgot(api, email)
    assert len(api.mail) == 1


@pytest.mark.contract
def test_password_endpoints_rate_limited(api):
    for _ in range(5):
        forgot(api, "unknown@example.com")
    r = api.post("/v1/auth/forgot-password", json={"email": "unknown@example.com"})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0
    assert_matches_contract(r)


def test_concurrent_reset_consumes_link_once(api):
    email, _, _ = register(api)
    forgot(api, email)
    token = api.mail[0][1]
    store = api.app.state.services.users
    hashed = hash_password(NEW_PASSWORD)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: store.reset_password(token, hashed), range(2)))
    assert sorted(results) == [False, True]
    assert store.get_by_email(email).user.auth_version == 1


def test_stale_login_or_refresh_cannot_resurrect_session(api):
    email, body, cookie = register(api)
    store = api.app.state.services.users
    old = store.get_by_email(email)
    refreshed_user = store.consume_refresh_token(cookie)
    assert refreshed_user
    assert store.change_password(old.user, old.password_hash, hash_password(NEW_PASSWORD))
    assert not store.add_refresh_token(refreshed_user, "stale-refresh", timedelta(days=1))
    store.update_password_hash(old.user.id, hash_password(PASSWORD), old.password_hash)
    assert verify_password(store.get_by_email(email).password_hash, NEW_PASSWORD)
    assert api.get("/v1/me", headers=bearer(body)).status_code == 401


def test_legacy_jwt_accepted_until_password_update(api):
    email, body, _ = register(api)
    claims = jwt.decode(body["access_token"], SECRET, algorithms=["HS256"])
    del claims["ver"]
    legacy = {"access_token": jwt.encode(claims, SECRET, algorithm="HS256")}
    assert api.get("/v1/me", headers=bearer(legacy)).status_code == 200
    forgot(api, email)
    assert reset(api, api.mail[0][1]).status_code == 204
    assert api.get("/v1/me", headers=bearer(legacy)).status_code == 401


def test_additive_schema_preserves_old_users_and_tokens(api):
    # A private schema models a database created before password recovery. Roll back the fixture.
    with api.app.state.services.users.pool.connection() as c:
        with c.transaction(force_rollback=True):
            c.execute("CREATE SCHEMA password_migration_test")
            c.execute("SET LOCAL search_path = password_migration_test")
            c.execute("CREATE TABLE users (id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
                      " email text UNIQUE NOT NULL, password_hash text NOT NULL,"
                      " created_at timestamptz NOT NULL DEFAULT now())")
            user = c.execute("INSERT INTO users (email, password_hash) VALUES ('old@example.com', 'hash')"
                             " RETURNING id").fetchone()
            c.execute(SCHEMA_SQL)
            c.execute("INSERT INTO refresh_tokens (token_hash, user_id, expires_at)"
                      " VALUES ('old-token', %s, now() + interval '1 day')", (user["id"],))
            c.execute(SCHEMA_SQL)
            assert c.execute("SELECT password_hash, auth_version FROM users").fetchone() == {
                "password_hash": "hash", "auth_version": 0,
            }
            assert c.execute("SELECT count(*) AS n FROM refresh_tokens").fetchone()["n"] == 1


@pytest.mark.parametrize("port,transport", [(587, "SMTP"), (2525, "SMTP"), (465, "SMTP_SSL")])
def test_brevo_smtp_transport_and_email(monkeypatch, port, transport):
    settings = Settings(smtp_username="smtp-login", smtp_password="smtp-key",
                        smtp_from_email="verified@example.com", smtp_port=port,
                        frontend_origin="https://fields.example.com")
    connection = MagicMock()
    smtp = connection.return_value.__enter__.return_value
    monkeypatch.setattr(f"app.auth.mail.smtplib.{transport}", connection)
    PasswordResetMailer(settings).send_reset("farmer@example.com", "private-reset-token")
    assert connection.call_args.args == ("smtp-relay.brevo.com", port)
    if port == 465:
        smtp.starttls.assert_not_called()
        assert connection.call_args.kwargs["context"].check_hostname
    else:
        smtp.starttls.assert_called_once()
        assert smtp.starttls.call_args.kwargs["context"].check_hostname
    smtp.login.assert_called_once_with("smtp-login", "smtp-key")
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == "farmer@example.com"
    assert message["From"] == "Field Shift <verified@example.com>"
    content = message.get_content()
    link = next(line for line in content.splitlines() if line.startswith("https://"))
    assert urlparse(link).netloc == "fields.example.com"
    assert parse_qs(urlparse(link).query) == {"token": ["private-reset-token"]}
    assert "one hour" in content and "smtp-key" not in content


def test_smtp_settings_accept_environment_values(monkeypatch):
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "")
    settings = Settings()
    assert settings.smtp_port == 587
    assert settings.smtp_from_email is None


@pytest.mark.parametrize("port", [25, 0, 65536])
def test_smtp_rejects_unsupported_ports(port):
    with pytest.raises(ValueError, match="smtp_port"):
        Settings(smtp_port=port)
