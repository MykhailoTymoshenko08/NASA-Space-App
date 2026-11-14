"""Users and refresh tokens in PostgreSQL (the same database as the CSB fields).

Tables are created on startup if missing (no migration tool in this project):
  users(id uuid PK, email text UNIQUE (stored lowercase), password_hash text, created_at)
  refresh_tokens(token_hash PK = sha256 of the opaque token, user_id FK, expires_at, created_at)

Refresh tokens are stored (hashed) rather than stateless so logout and rotation really revoke them.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

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
"""


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    created_at: datetime


@dataclass(frozen=True)
class UserWithHash:
    user: User
    password_hash: str


class EmailTaken(Exception):
    pass


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _user(row: dict) -> User:
    return User(id=row["id"], email=row["email"], created_at=row["created_at"])


class UserStore:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    @classmethod
    def connect(cls, url: str) -> "UserStore | None":
        """Open a pool and create the tables if missing. None (with a log line) when the DB is unusable."""
        pool = ConnectionPool(url, min_size=1, max_size=4, open=False, kwargs={"row_factory": dict_row})
        try:
            pool.open(wait=True, timeout=5)
            with pool.connection() as c:
                c.execute(SCHEMA_SQL)
        except Exception as e:  # noqa: BLE001 - any DB failure means "auth unavailable"
            log.error("auth database unavailable at %s (%s): auth endpoints return 500",
                      url.split("@")[-1], e)
            pool.close()
            return None
        return cls(pool)

    def close(self) -> None:
        self._pool.close()

    def create_user(self, email: str, password_hash: str) -> User:
        try:
            with self._pool.connection() as c:
                row = c.execute(
                    "INSERT INTO users (email, password_hash) VALUES (%s, %s)"
                    " RETURNING id, email, created_at",
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
            row = c.execute("SELECT id, email, created_at FROM users WHERE id = %s", (user_id,)).fetchone()
        return _user(row) if row else None

    def update_password_hash(self, user_id: UUID, password_hash: str) -> None:
        with self._pool.connection() as c:
            c.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))

    def add_refresh_token(self, user_id: UUID, token: str, ttl: timedelta) -> None:
        with self._pool.connection() as c:
            # Housekeeping: drop this user's expired tokens so the table does not grow forever.
            c.execute("DELETE FROM refresh_tokens WHERE user_id = %s AND expires_at <= now()", (user_id,))
            c.execute(
                "INSERT INTO refresh_tokens (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                (token_digest(token), user_id, datetime.now(UTC) + ttl),
            )

    def consume_refresh_token(self, token: str) -> UUID | None:
        """Delete the token and return its user id if it was valid. Single use: a second call gets None."""
        with self._pool.connection() as c:
            row = c.execute(
                "DELETE FROM refresh_tokens WHERE token_hash = %s RETURNING user_id, expires_at",
                (token_digest(token),),
            ).fetchone()
        if not row or row["expires_at"] <= datetime.now(UTC):
            return None
        return row["user_id"]

    def revoke_refresh_token(self, token: str) -> None:
        with self._pool.connection() as c:
            c.execute("DELETE FROM refresh_tokens WHERE token_hash = %s", (token_digest(token),))
