"""Tiny cache interface: in-process TTL cache in front of `diskcache` on disk.

Swap `TwoLevelCache` for a Redis-backed `Cache` later without touching callers.
"""

import threading
from pathlib import Path
from typing import Any, Protocol

import diskcache
from cachetools import TTLCache


class Cache(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl_s: int) -> None: ...


class MemoryCache:
    def __init__(self, maxsize: int = 2048, ttl_s: int = 3600):
        self._c: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_s)
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            return self._c.get(key)

    def set(self, key: str, value: Any, ttl_s: int) -> None:
        # cachetools uses one TTL per cache; the memory layer is short-lived on purpose.
        with self._lock:
            self._c[key] = value


class TwoLevelCache:
    def __init__(self, directory: Path, memory_ttl_s: int = 3600):
        directory.mkdir(parents=True, exist_ok=True)
        self._mem = MemoryCache(ttl_s=memory_ttl_s)
        self._disk = diskcache.Cache(str(directory))

    def get(self, key: str) -> Any | None:
        v = self._mem.get(key)
        if v is not None:
            return v
        v = self._disk.get(key)
        if v is not None:
            self._mem.set(key, v, 0)
        return v

    def set(self, key: str, value: Any, ttl_s: int) -> None:
        self._mem.set(key, value, ttl_s)
        self._disk.set(key, value, expire=ttl_s)

    def close(self) -> None:
        self._disk.close()
