"""Expiry, safe serialization and restart behavior of the disposable data cache."""

import sqlite3

import pytest

from app.core.cache import MemoryCache, TwoLevelCache


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("app.core.cache.time.time", lambda: now[0])
    monkeypatch.setattr("app.core.cache.time.monotonic", lambda: now[0])
    return now


def test_memory_respects_each_entry_lifetime(clock):
    cache = MemoryCache(ttl_s=3600)
    cache.set("short", "short", 1)
    cache.set("long", "long", 10)
    clock[0] += 2
    assert cache.get("short") is None
    assert cache.get("long") == "long"
    cache.set("long", "replacement", 0)
    assert cache.get("long") is None


def test_disk_promotion_preserves_remaining_expiry(tmp_path, clock):
    first = TwoLevelCache(tmp_path)
    first.set("data", {"value": 42}, 10)
    first.close()
    second = TwoLevelCache(tmp_path)
    clock[0] += 9
    assert second.get("data") == {"value": 42}
    clock[0] += 2
    assert second.get("data") is None
    second.close()


def test_legacy_cache_and_corrupt_json_are_never_unpickled(tmp_path, clock):
    (tmp_path / "cache.db").write_bytes(b"legacy pickle cache must not be opened")
    cache = TwoLevelCache(tmp_path)
    assert cache.get("old") is None
    with sqlite3.connect(tmp_path / "cache-v2.sqlite3") as db:
        db.execute("INSERT INTO cache_entries VALUES (?, ?, ?)", ("bad", "not JSON", clock[0] + 10))
    assert cache.get("bad") is None
    cache.close()


def test_cache_bounds_disk_rows_and_expires_memory(tmp_path, clock):
    cache = TwoLevelCache(tmp_path, max_entries=2)
    for i in range(3):
        cache.set(str(i), i, 10 + i)
    with sqlite3.connect(tmp_path / "cache-v2.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM cache_entries").fetchone()[0] == 2
    clock[0] += 20
    assert cache.get("2") is None
    cache.close()
