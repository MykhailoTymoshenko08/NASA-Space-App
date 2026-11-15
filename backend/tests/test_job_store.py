"""Job persistence, retention, capacity and report rendering across independent API workers."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import psycopg
import pytest

from app.analyses.store import InMemoryJobStore, JobRecord, PostgresJobStore
from app.core.errors import ApiException, ErrorCode
from app.models import AnalysisJob, AnalysisOptions, JobStatus, Progress


def record(status=JobStatus.succeeded, **kw):
    return JobRecord(
        job=AnalysisJob(
            job_id=str(uuid.uuid4()), status=status, created_at=datetime.now(UTC),
            progress=Progress(percent=100 if status == JobStatus.succeeded else 0, stage="Probe"),
        ),
        dedupe_key=str(uuid.uuid4()), **kw,
    )


@pytest.fixture
def stores(db_url):
    with psycopg.connect(db_url) as c:
        c.execute("DROP TABLE IF EXISTS analysis_jobs")
    first = PostgresJobStore.connect(db_url)
    second = PostgresJobStore.connect(db_url)
    try:
        yield first, second
    finally:
        first.close()
        second.close()


def test_postgres_jobs_options_owners_and_reports_survive_new_store(stores, db_url):
    first, second = stores
    owner = uuid.uuid4()
    rec = record(owner_id=owner, options=AnalysisOptions(horizon_years=5, priorities=["soil_health"]))
    rec.job.options = rec.options
    first.put(rec)
    loaded = second.get(rec.job.job_id)
    assert loaded.job == rec.job and loaded.options == rec.options and loaded.owner_id == owner
    assert second.find_recent(rec.dedupe_key, 60).job == rec.job
    assert first.report(rec.job.job_id, lambda _: b"%PDF-shared") == b"%PDF-shared"
    # A stale worker's progress save must never overwrite a PDF produced by another worker.
    loaded.job.progress.stage = "Persisted"
    second.save(loaded)
    first.close()
    third = PostgresJobStore.connect(db_url)
    try:
        restored = third.get(rec.job.job_id)
        assert restored.owner_id == owner and restored.options == rec.options
        assert restored.job.progress.stage == "Persisted"
        pdf = third.report(rec.job.job_id, lambda _: pytest.fail("rendered a cached report"))
        assert pdf == b"%PDF-shared"
    finally:
        third.close()


def test_postgres_backfills_options_for_older_job_json(stores):
    first, second = stores
    rec = record(options=AnalysisOptions(horizon_years=4))
    assert rec.job.options is None
    first.put(rec)
    loaded = second.get(rec.job.job_id)
    assert loaded.job.options == rec.options
    assert loaded.options == rec.options


def test_postgres_unavailable_database_does_not_fall_back(monkeypatch):
    class UnavailablePool:
        closed = False

        def open(self, **kw):
            raise RuntimeError("database is down")

        def close(self):
            self.closed = True

    pool = UnavailablePool()
    monkeypatch.setattr("app.analyses.store.open_pool", lambda *args, **kw: pool)
    with pytest.raises(RuntimeError, match="refusing to lose jobs in memory"):
        PostgresJobStore.connect("postgresql://unavailable")
    assert pool.closed


def test_postgres_first_report_is_rendered_once_across_stores(stores):
    first, second = stores
    rec = record()
    first.put(rec)
    barrier = threading.Barrier(2)
    count = 0
    lock = threading.Lock()

    def render(_):
        nonlocal count
        with lock:
            count += 1
        time.sleep(0.05)
        return b"%PDF-once"

    def download(store):
        barrier.wait(timeout=5)
        return store.report(rec.job.job_id, render)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(download, (first, second)))
    assert results == [b"%PDF-once", b"%PDF-once"] and count == 1


def test_postgres_expiry_is_enforced_without_another_insert(stores, db_url):
    first, second = stores
    rec = record()
    first.put(rec)
    with psycopg.connect(db_url) as c:
        c.execute("UPDATE analysis_jobs SET expires_at = now() - interval '1 second' WHERE id = %s",
                  (uuid.UUID(rec.job.job_id),))
    assert second.get(rec.job.job_id) is None
    assert second.find_recent(rec.dedupe_key, 3600) is None
    with pytest.raises(ApiException) as error:
        second.report(rec.job.job_id, lambda _: pytest.fail("rendered an expired job"))
    assert error.value.status_code == 404
    assert second.get("not-a-uuid") is None


def test_postgres_capacity_rejects_active_and_evicts_finished(stores):
    first, second = stores
    first.max_jobs = second.max_jobs = 1
    active = record(JobStatus.running)
    first.put(active)
    with pytest.raises(ApiException) as error:
        second.put(record())
    assert error.value.code == ErrorCode.RATE_LIMITED and error.value.headers["Retry-After"] == "60"
    assert first.get(active.job.job_id).job.status == JobStatus.running
    active.job.status = JobStatus.succeeded
    first.save(active)
    next_job = record()
    second.put(next_job)
    assert first.get(active.job.job_id) is None
    assert first.get(next_job.job.job_id) is not None


def test_postgres_capacity_is_shared_between_concurrent_workers(stores):
    first, second = stores
    first.max_jobs = second.max_jobs = 1
    barrier = threading.Barrier(2)

    def insert(store):
        barrier.wait(timeout=5)
        try:
            store.put(record(JobStatus.running))
        except ApiException as exc:
            return exc.code
        return "stored"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(insert, (first, second)))
    assert results.count("stored") == 1 and results.count(ErrorCode.RATE_LIMITED) == 1


@pytest.mark.parametrize("kind", ["memory", "postgres"])
def test_report_cache_has_a_total_byte_budget(kind, stores):
    store = InMemoryJobStore(max_pdf_bytes=4) if kind == "memory" else stores[0]
    store.max_pdf_bytes = 4
    first, second = record(), record()
    store.put(first)
    store.put(second)
    assert store.report(first.job.job_id, lambda _: b"one") == b"one"
    assert store.report(second.job.job_id, lambda _: b"two") == b"two"
    assert store.get(first.job.job_id).report_pdf is None
    assert store.get(second.job.job_id).report_pdf == b"two"
    assert store.report(first.job.job_id, lambda _: b"oversized") == b"oversized"
    assert store.get(first.job.job_id).report_pdf is None


def test_memory_expiry_is_enforced_on_reads(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.analyses.store.time.monotonic", lambda: clock[0])
    store = InMemoryJobStore(retention_s=1)
    rec = record(created_mono=100.0)
    store.put(rec)
    assert store.get(rec.job.job_id) is rec
    clock[0] = 101.0
    assert store.get(rec.job.job_id) is None
    assert store.find_recent(rec.dedupe_key, 60) is None


def test_memory_capacity_preserves_active_and_evicts_finished():
    store = InMemoryJobStore(max_jobs=1)
    active = record(JobStatus.running)
    store.put(active)
    with pytest.raises(ApiException) as error:
        store.put(record())
    assert error.value.code == ErrorCode.RATE_LIMITED
    active.job.status = JobStatus.failed
    store.save(active)
    replacement = record()
    store.put(replacement)
    assert store.get(active.job.job_id) is None and store.get(replacement.job.job_id) is replacement


def test_memory_first_report_is_rendered_once_and_save_preserves_cache():
    store = InMemoryJobStore()
    rec = record(owner_id=uuid.uuid4())
    store.put(rec)
    count = 0

    def render(_):
        nonlocal count
        count += 1
        time.sleep(0.02)
        return b"%PDF-once"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.report(rec.job.job_id, render), range(2)))
    assert results == [b"%PDF-once", b"%PDF-once"] and count == 1
    stale = record()
    stale.job = rec.job.model_copy(update={"progress": Progress(percent=100, stage="Saved")})
    store.save(stale)
    assert store.get(rec.job.job_id).report_pdf == b"%PDF-once"
    assert store.get(rec.job.job_id).owner_id == rec.owner_id
