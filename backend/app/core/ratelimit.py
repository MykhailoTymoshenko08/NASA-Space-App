"""Bounded sliding-window quotas, in memory or shared through PostgreSQL."""

import math
import threading
import time
from collections import OrderedDict, deque

from fastapi import Request
from psycopg_pool import ConnectionPool

from app.auth.tokens import TokenExpired, TokenInvalid, decode_access_token
from app.core.errors import ApiException, ErrorCode


def _limited(seconds: float) -> ApiException:
    retry = max(1, math.ceil(seconds))
    return ApiException(
        ErrorCode.RATE_LIMITED,
        f"Too many requests. Try again in {retry} s.",
        {"retry_after_s": retry},
        headers={"Retry-After": str(retry)},
    )


class RateLimiter:
    def __init__(self, limit: int, window_s: int, max_keys: int = 10000):
        if min(limit, window_s, max_keys) <= 0:
            raise ValueError("Rate-limit count, window and key capacity must be positive")
        self.limit = limit
        self.window_s = window_s
        self.max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> None:
        with self._lock:
            now = time.monotonic() if now is None else now
            cutoff = now - self.window_s
            # Accepted hits keep keys ordered by last activity; expired clients leave no permanent entry.
            while self._hits and next(iter(self._hits.values()))[-1] <= cutoff:
                self._hits.popitem(last=False)
            q = self._hits.get(key)
            if q is None:
                if len(self._hits) >= self.max_keys:
                    # Evicting a live quota lets new keys reset it. Refuse enrollment until a slot expires.
                    oldest = next(iter(self._hits.values()))[-1]
                    raise _limited(oldest + self.window_s - now)
                q = deque()
                self._hits[key] = q
            while q and q[0] <= now - self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                raise _limited(q[0] + self.window_s - now)
            q.append(now)
            self._hits.move_to_end(key)


class PostgreSQLRateLimiter:
    """The same quota across workers; the caller owns the already-open connection pool."""

    def __init__(self, pool: ConnectionPool, bucket: str, limit: int, window_s: int, max_keys: int = 10000):
        if min(limit, window_s, max_keys) <= 0:
            raise ValueError("Rate-limit count, window and key capacity must be positive")
        self._pool = pool
        self.bucket, self.limit, self.window_s, self.max_keys = bucket, limit, window_s, max_keys
        with pool.connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS request_limits (
                    bucket text NOT NULL,
                    client_key text NOT NULL,
                    hits double precision[] NOT NULL,
                    updated_at timestamptz NOT NULL,
                    PRIMARY KEY (bucket, client_key)
                );
                CREATE INDEX IF NOT EXISTS request_limits_updated_idx ON request_limits (bucket, updated_at);
            """)

    def check(self, key: str, now: float | None = None) -> None:
        # Shared storage needs wall time: monotonic clocks are unrelated across processes and hosts.
        now = float(time.time() if now is None else now)
        with self._pool.connection() as connection:
            connection.execute(
                "DELETE FROM request_limits WHERE bucket = %s AND updated_at <= to_timestamp(%s)",
                (self.bucket, now - self.window_s),
            )
            row = connection.execute(
                "SELECT hits FROM request_limits WHERE bucket = %s AND client_key = %s FOR UPDATE",
                (self.bucket, key),
            ).fetchone()
            if row is None:
                # Serialize only enrollment so simultaneous new clients cannot exceed the key cap.
                connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                                   ("fieldshift:rate-limit:" + self.bucket,))
                row = connection.execute(
                    "SELECT hits FROM request_limits WHERE bucket = %s AND client_key = %s FOR UPDATE",
                    (self.bucket, key),
                ).fetchone()
                if row is None:
                    size = connection.execute(
                        "SELECT count(*) AS total, min(extract(epoch FROM updated_at)) AS oldest"
                        " FROM request_limits WHERE bucket = %s", (self.bucket,),
                    ).fetchone()
                    if size["total"] >= self.max_keys:
                        raise _limited(float(size["oldest"]) + self.window_s - now)
                    connection.execute(
                        "INSERT INTO request_limits (bucket, client_key, hits, updated_at)"
                        " VALUES (%s, %s, '{}'::double precision[], to_timestamp(%s))",
                        (self.bucket, key, now),
                    )
            hits = [hit for hit in row["hits"] if hit > now - self.window_s] if row is not None else []
            if len(hits) >= self.limit:
                raise _limited(min(hits) + self.window_s - now)
            hits = sorted([*hits, now])
            connection.execute(
                "UPDATE request_limits SET hits = %s, updated_at = to_timestamp(%s)"
                " WHERE bucket = %s AND client_key = %s",
                (hits, hits[-1], self.bucket, key),
            )


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limited(bucket: str):
    """FastAPI dependency factory. One limiter per bucket, stored on app.state."""

    def dep(request: Request) -> None:
        key = "ip:" + client_ip(request)
        svc = getattr(request.app.state, "services", None)
        users = getattr(svc, "users", None)
        secret = getattr(svc, "jwt_secret", None)
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if bucket not in {"auth", "password"} and users is not None and secret and scheme.lower() == "bearer":
            try:
                user_id, version = decode_access_token(token.strip(), secret)
            except (TokenExpired, TokenInvalid):
                pass
            else:
                user = users.get_by_id(user_id)
                if user is not None and user.id == user_id and user.auth_version == version:
                    key = f"user:{user_id}"
        request.app.state.limiters[bucket].check(key)

    return dep
