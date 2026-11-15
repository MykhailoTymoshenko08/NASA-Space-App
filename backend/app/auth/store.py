"""Users and refresh tokens in PostgreSQL (the same database as the CSB fields).

Tables are created on startup if missing (no migration tool in this project):
  users(id uuid PK, email text UNIQUE (stored lowercase), password_hash text, created_at)
  refresh_tokens(token_hash PK = sha256 of the opaque token, user_id FK, expires_at, created_at)
  password_reset_tokens(user_id PK/FK, token_hash UNIQUE, expires_at, requested_at)

An additive users.auth_version column revokes all access tokens when a password is updated.

Refresh tokens are stored (hashed) rather than stateless so logout and rotation really revoke them.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
from psycopg_pool import ConnectionPool

from app.core.db import open_pool

log = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash text PRIMARY KEY,
    user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS refresh_tokens_user_idx ON refresh_tokens (user_id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_version integer NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT now()
);
"""


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    created_at: datetime
    auth_version: int = 0


@dataclass(frozen=True)
class UserWithHash:
    user: User
    password_hash: str


class EmailTaken(Exception):
    pass


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _user(row: dict) -> User:
    return User(id=row["id"], email=row["email"], created_at=row["created_at"],
                auth_version=row["auth_version"])


class UserStore:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    @classmethod
    def connect(cls, url: str) -> "UserStore | None":
        """Open a pool and create the tables if missing. None (with a log line) when the DB is unusable."""
        pool = open_pool(url, max_size=4)
        try:
            pool.open(wait=True, timeout=5)
            with pool.connection(timeout=5) as c:
                c.execute(SCHEMA_SQL)
        except Exception as e:  # noqa: BLE001 - any DB failure means "auth unavailable"
            log.error("auth database unavailable at %s (%s): auth endpoints return 500",
                      url.split("@")[-1], e)
            pool.close()
            return None
        return cls(pool)

    @property
    def pool(self) -> ConnectionPool:
        """Shared with SavedFieldStore: same database, and its table references `users`."""
        return self._pool

    def close(self) -> None:
        self._pool.close()

    def create_user(self, email: str, password_hash: str) -> User:
        try:
            with self._pool.connection() as c:
                row = c.execute(
                    "INSERT INTO users (email, password_hash) VALUES (%s, %s)"
                    " RETURNING id, email, created_at, auth_version",
                    (email, password_hash),
                ).fetchone()
        except psycopg.errors.UniqueViolation as e:
            raise EmailTaken(email) from e
        return _user(row)

    def get_by_email(self, email: str) -> UserWithHash | None:
        with self._pool.connection() as c:
            row = c.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
        return UserWithHash(_user(row), row["password_hash"]) if row else None

    def get_by_id(self, user_id: UUID) -> User | None:
        with self._pool.connection() as c:
            row = c.execute(
                "SELECT id, email, created_at, auth_version FROM users WHERE id = %s", (user_id,)
            ).fetchone()
        return _user(row) if row else None

    def update_password_hash(self, user_id: UUID, password_hash: str, expected_hash: str) -> None:
        with self._pool.connection() as c:
            # A login rehash must never overwrite a password changed by a concurrent reset.
            c.execute("UPDATE users SET password_hash = %s WHERE id = %s AND password_hash = %s",
                      (password_hash, user_id, expected_hash))

    def add_refresh_token(self, user: User, token: str, ttl: timedelta) -> bool:
        with self._pool.connection() as c:
            row = c.execute("SELECT auth_version FROM users WHERE id = %s FOR UPDATE",
                            (user.id,)).fetchone()
            if row is None or row["auth_version"] != user.auth_version:
                return False
            # Housekeeping: drop this user's expired tokens so the table does not grow forever.
            c.execute("DELETE FROM refresh_tokens WHERE user_id = %s AND expires_at <= now()", (user.id,))
            c.execute(
                "INSERT INTO refresh_tokens (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                (token_digest(token), user.id, datetime.now(UTC) + ttl),
            )
        return True

    def consume_refresh_token(self, token: str) -> User | None:
        """Delete the token and return its user if it was valid. Single use: a second call gets None."""
        with self._pool.connection() as c:
            # Lock the user before changing tokens, consistently with password updates. Capture the
            # version now so a concurrent password reset cannot resurrect this refresh session.
            user = c.execute(
                "SELECT u.* FROM users u JOIN refresh_tokens r ON r.user_id = u.id"
                " WHERE r.token_hash = %s FOR UPDATE OF u", (token_digest(token),),
            ).fetchone()
            row = c.execute(
                "DELETE FROM refresh_tokens WHERE token_hash = %s RETURNING user_id, expires_at",
                (token_digest(token),),
            ).fetchone()
        if not user or not row or row["expires_at"] <= datetime.now(UTC):
            return None
        return _user(user)

    def revoke_refresh_token(self, token: str) -> None:
        with self._pool.connection() as c:
            c.execute("DELETE FROM refresh_tokens WHERE token_hash = %s", (token_digest(token),))

    @staticmethod
    def _replace_password(c: psycopg.Connection, user_id: UUID, password_hash: str) -> None:
        c.execute("UPDATE users SET password_hash = %s, auth_version = auth_version + 1 WHERE id = %s",
                  (password_hash, user_id))
        c.execute("DELETE FROM refresh_tokens WHERE user_id = %s", (user_id,))
        c.execute("DELETE FROM password_reset_tokens WHERE user_id = %s", (user_id,))

    def change_password(self, user: User, expected_hash: str, password_hash: str) -> bool:
        with self._pool.connection() as c:
            row = c.execute("SELECT password_hash, auth_version FROM users WHERE id = %s FOR UPDATE",
                            (user.id,)).fetchone()
            if not row or row["password_hash"] != expected_hash or row["auth_version"] != user.auth_version:
                return False
            self._replace_password(c, user.id, password_hash)
        return True

    def create_password_reset(self, email: str, token: str) -> User | None:
        """Replace a link, at most once per minute per account. Store only its digest, for one hour."""
        with self._pool.connection() as c:
            user = c.execute("SELECT * FROM users WHERE email = %s FOR UPDATE", (email,)).fetchone()
            if user is None:
                return None
            row = c.execute(
                "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)"
                " VALUES (%s, %s, now() + interval '1 hour')"
                " ON CONFLICT (user_id) DO UPDATE SET token_hash = EXCLUDED.token_hash,"
                " expires_at = EXCLUDED.expires_at, requested_at = now()"
                " WHERE password_reset_tokens.requested_at <= now() - interval '1 minute'"
                " RETURNING user_id", (user["id"], token_digest(token)),
            ).fetchone()
        return _user(user) if row else None

    def discard_password_reset(self, token: str) -> None:
        with self._pool.connection() as c:
            c.execute("DELETE FROM password_reset_tokens WHERE token_hash = %s", (token_digest(token),))

    def reset_password(self, token: str, password_hash: str) -> bool:
        """Consume a valid link and update credentials in one transaction. User lock prevents replay."""
        with self._pool.connection() as c:
            row = c.execute("SELECT user_id FROM password_reset_tokens WHERE token_hash = %s",
                            (token_digest(token),)).fetchone()
            if not row:
                return False
            c.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (row["user_id"],))
            valid = c.execute(
                "DELETE FROM password_reset_tokens WHERE token_hash = %s AND expires_at > now()"
                " RETURNING user_id", (token_digest(token),),
            ).fetchone()
            if not valid:
                return False
            self._replace_password(c, valid["user_id"], password_hash)
        return True
