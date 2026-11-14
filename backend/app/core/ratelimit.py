"""Simple per-IP sliding-window rate limiter (in-memory, single process)."""

import math
import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import ApiException, ErrorCode


class RateLimiter:
    def __init__(self, limit: int, window_s: int):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                retry = max(1, math.ceil(q[0] + self.window_s - now))
                raise ApiException(
                    ErrorCode.RATE_LIMITED,
                    f"Too many requests. Try again in {retry} s.",
                    {"retry_after_s": retry},
                    headers={"Retry-After": str(retry)},
                )
            q.append(now)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limited(bucket: str):
    """FastAPI dependency factory. One limiter per bucket, stored on app.state."""

    def dep(request: Request) -> None:
        limiter: RateLimiter = request.app.state.limiters[bucket]
        limiter.check(client_ip(request))

    return dep
