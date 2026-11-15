"""Bounded JSON caches with per-entry expiry in memory and SQLite.

The SQLite file is separate from legacy diskcache files: existing pickle caches are never read.
Removing cache-v2.sqlite3 safely clears the disposable cache; old deployments can still use their cache.
"""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from cachetools import TLRUCache


class Cache(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl_s: int) -> None: ...


class MemoryCache:
    def __init__(self, maxsize: int = 2048, ttl_s: int = 3600):
        self.ttl_s = ttl_s
        self._c = TLRUCache(maxsize=maxsize, ttu=lambda _key, value, _now: value[0],
                            timer=lambda: time.monotonic())
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._c.get(key)
            return entry[1] if entry is not None else None

    def set(self, key: str, value: Any, ttl_s: float) -> None:
        # Each entry respects both its requested lifetime and the memory layer's shorter lifetime.
        with self._lock:
            if ttl_s <= 0:
                self._c.pop(key, None)
            else:
                self._c[key] = (time.monotonic() + min(self.ttl_s, ttl_s), value)


class TwoLevelCache:
    def __init__(self, directory: Path, memory_ttl_s: int = 3600, max_entries: int = 8192):
        directory.mkdir(parents=True, exist_ok=True)
        self._mem = MemoryCache(ttl_s=memory_ttl_s)
        self._lock = threading.Lock()
        self.max_entries = max_entries
        self._db = sqlite3.connect(directory / "cache-v2.sqlite3", check_same_thread=False, timeout=5)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache_entries "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL NOT NULL)"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS cache_expiry ON cache_entries(expires_at)")
        self._db.commit()

    def get(self, key: str) -> Any | None:
        value = self._mem.get(key)
        if value is not None:
            return value
        now = time.time()
        with self._lock:
            row = self._db.execute(
                "SELECT value, expires_at FROM cache_entries WHERE key = ? AND expires_at > ?", (key, now)
            ).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row[0])
        except (ValueError, TypeError):
            return None  # Corrupt cache data is a miss, never executable Python.
        self._mem.set(key, value, max(0, row[1] - time.time()))
        return value

    def set(self, key: str, value: Any, ttl_s: int) -> None:
        payload = json.dumps(value, allow_nan=False)
        now = time.time()
        with self._lock, self._db:
            self._db.execute("DELETE FROM cache_entries WHERE expires_at <= ? OR key = ?", (now, key))
            if ttl_s > 0:
                self._db.execute("INSERT INTO cache_entries VALUES (?, ?, ?)", (key, payload, now + ttl_s))
                self._db.execute(
                    "DELETE FROM cache_entries WHERE key IN "
                    "(SELECT key FROM cache_entries ORDER BY expires_at DESC LIMIT -1 OFFSET ?)",
                    (self.max_entries,),
                )
        self._mem.set(key, value, ttl_s)

    def close(self) -> None:
        with self._lock:
            self._db.close()
