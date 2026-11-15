"""Bounded analysis storage, shared through PostgreSQL when a database is configured."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.core.db import open_pool
from app.core.errors import ApiException, ErrorCode, not_found
from app.models import AnalysisJob, AnalysisOptions

JOB_RETENTION_S = 86400
MAX_JOBS = 1000
MAX_PDF_BYTES = 8 * 1024 * 1024
_FINISHED = {"succeeded", "failed"}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id uuid PRIMARY KEY,
    dedupe_key text NOT NULL,
    job jsonb NOT NULL,
    options jsonb,
    owner_id uuid,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    report_pdf bytea
);
CREATE INDEX IF NOT EXISTS analysis_jobs_dedupe_idx ON analysis_jobs (dedupe_key, created_at DESC);
CREATE INDEX IF NOT EXISTS analysis_jobs_expiry_idx ON analysis_jobs (expires_at);
"""


def _capacity_error() -> ApiException:
    return ApiException(
        ErrorCode.RATE_LIMITED,
        "All analysis slots are busy. Please try again in a minute.",
        {"retry_after_s": 60}, headers={"Retry-After": "60"},
    )


def _valid_limits(retention_s: float, max_jobs: int, max_pdf_bytes: int) -> None:
    if retention_s <= 0 or max_jobs < 1 or max_pdf_bytes < 0:
        raise ValueError("Job retention and capacity must be positive; PDF cache capacity cannot be negative")


def _job_id(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (ValueError, TypeError, AttributeError):
        return None


@dataclass
class JobRecord:
    job: AnalysisJob
    dedupe_key: str
    created_mono: float = field(default_factory=time.monotonic)
    # The farmer's choices, kept for the PDF report (the result itself does not echo them).
    options: AnalysisOptions | None = None
    # The rendered PDF report, made on first download: a finished job never changes.
    report_pdf: bytes | None = None
    owner_id: UUID | None = None
    report_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)


ReportRenderer = Callable[[JobRecord], bytes]


class JobStore(Protocol):
    def get(self, job_id: str) -> JobRecord | None: ...
    def put(self, rec: JobRecord) -> None: ...
    def find_recent(self, dedupe_key: str, max_age_s: float) -> JobRecord | None: ...
    def save(self, rec: JobRecord) -> None: ...
    def report(self, job_id: str, render: ReportRenderer) -> bytes: ...
    def close(self) -> None: ...


class InMemoryJobStore:
    def __init__(
        self, retention_s: float = JOB_RETENTION_S,
        max_jobs: int = MAX_JOBS, max_pdf_bytes: int = MAX_PDF_BYTES,
    ):
        _valid_limits(retention_s, max_jobs, max_pdf_bytes)
        self._jobs: dict[str, JobRecord] = {}
        self._by_key: dict[str, str] = {}
        self.retention_s = retention_s
        self.max_jobs = max_jobs
        self.max_pdf_bytes = max_pdf_bytes
        self._lock = threading.RLock()

    def _remove(self, job_id: str) -> None:
        rec = self._jobs.pop(job_id)
        if self._by_key.get(rec.dedupe_key) == job_id:
            del self._by_key[rec.dedupe_key]

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.retention_s
        for jid in [j for j, r in self._jobs.items() if r.created_mono <= cutoff]:
            self._remove(jid)

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            self._prune()
            return self._jobs.get(job_id)

    def put(self, rec: JobRecord) -> None:
        with self._lock:
            self._prune()
            if rec.job.job_id in self._jobs:
                self.save(rec)
                return
            while len(self._jobs) >= self.max_jobs:
                finished = [r for r in self._jobs.values() if r.job.status in _FINISHED]
                if not finished:
                    raise _capacity_error()
                self._remove(min(finished, key=lambda r: r.created_mono).job.job_id)
            pdf, rec.report_pdf = rec.report_pdf, None
            self._jobs[rec.job.job_id] = rec
            self._by_key[rec.dedupe_key] = rec.job.job_id
            if pdf is not None:
                self._cache_report(rec, pdf)

    def save(self, rec: JobRecord) -> None:
        with self._lock:
            stored = self.get(rec.job.job_id)
            if stored is not None:
                stored.job, stored.options = rec.job, rec.options

    def find_recent(self, dedupe_key: str, max_age_s: float) -> JobRecord | None:
        with self._lock:
            self._prune()
            jid = self._by_key.get(dedupe_key)
            rec = self._jobs.get(jid) if jid else None
            if rec and time.monotonic() - rec.created_mono <= max_age_s:
                return rec
            return None

    def _cache_report(self, rec: JobRecord, pdf: bytes) -> None:
        if len(pdf) > self.max_pdf_bytes:
            return
        total = sum(len(r.report_pdf or b"") for r in self._jobs.values())
        for old in sorted(self._jobs.values(), key=lambda r: r.created_mono):
            if total + len(pdf) <= self.max_pdf_bytes:
                break
            total -= len(old.report_pdf or b"")
            old.report_pdf = None
        rec.report_pdf = pdf

    def report(self, job_id: str, render: ReportRenderer) -> bytes:
        rec = self.get(job_id)
        if rec is None:
            raise not_found("Analysis job not found.", job_id=job_id)
        with rec.report_lock:
            with self._lock:
                if self.get(job_id) is not rec:
                    raise not_found("Analysis job not found.", job_id=job_id)
                if rec.report_pdf is not None:
                    return rec.report_pdf
            pdf = render(rec)
            with self._lock:
                if self.get(job_id) is rec:
                    self._cache_report(rec, pdf)
            return pdf

    def close(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._by_key.clear()


def _advisory_lock(connection, key: str) -> None:
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))


class PostgresJobStore:
    """Job JSON and PDFs shared by API workers; report rendering locks are transaction-scoped."""

    def __init__(
        self, pool: ConnectionPool, retention_s: float = JOB_RETENTION_S,
        max_jobs: int = MAX_JOBS, max_pdf_bytes: int = MAX_PDF_BYTES,
    ):
        _valid_limits(retention_s, max_jobs, max_pdf_bytes)
        self._pool = pool
        self.retention_s = retention_s
        self.max_jobs = max_jobs
        self.max_pdf_bytes = max_pdf_bytes

    @classmethod
    def connect(
        cls, url: str, retention_s: float = JOB_RETENTION_S,
        max_jobs: int = MAX_JOBS, max_pdf_bytes: int = MAX_PDF_BYTES,
    ) -> "PostgresJobStore":
        _valid_limits(retention_s, max_jobs, max_pdf_bytes)
        pool = open_pool(url, max_size=4)
        try:
            pool.open(wait=True, timeout=5)
            with pool.connection(timeout=5) as c:
                _advisory_lock(c, "fieldshift:analysis_jobs:schema")
                c.execute(SCHEMA_SQL)
        except Exception as exc:
            pool.close()
            raise RuntimeError(
                "Analysis job database is unavailable; refusing to lose jobs in memory"
            ) from exc
        return cls(pool, retention_s, max_jobs, max_pdf_bytes)

    @property
    def pool(self) -> ConnectionPool:
        """Shared by database-backed state that must use the same lifecycle as the job store."""
        return self._pool

    @staticmethod
    def _record(row: dict) -> JobRecord:
        age = (datetime.now(UTC) - row["created_at"]).total_seconds()
        job = AnalysisJob.model_validate(row["job"])
        options = AnalysisOptions.model_validate(row["options"]) if row["options"] is not None else None
        if job.options is None and options is not None:
            job.options = options
        return JobRecord(
            job=job, dedupe_key=row["dedupe_key"],
            created_mono=time.monotonic() - age,
            options=options,
            report_pdf=bytes(row["report_pdf"]) if row["report_pdf"] is not None else None,
            owner_id=row["owner_id"],
        )

    def get(self, job_id: str) -> JobRecord | None:
        jid = _job_id(job_id)
        if jid is None:
            return None
        with self._pool.connection() as c:
            row = c.execute(
                "SELECT * FROM analysis_jobs WHERE id = %s AND expires_at > now()", (jid,),
            ).fetchone()
        return self._record(row) if row else None

    def put(self, rec: JobRecord) -> None:
        age = time.monotonic() - rec.created_mono
        created = datetime.now(UTC) - timedelta(seconds=age)
        with self._pool.connection() as c:
            _advisory_lock(c, "fieldshift:analysis_jobs:capacity")
            c.execute("DELETE FROM analysis_jobs WHERE expires_at <= now()")
            if c.execute("SELECT 1 FROM analysis_jobs WHERE id = %s", (UUID(rec.job.job_id),)).fetchone():
                self._save(c, rec)
                return
            count = c.execute("SELECT count(*) AS n FROM analysis_jobs").fetchone()["n"]
            if count >= self.max_jobs:
                victims = c.execute(
                    "SELECT id FROM analysis_jobs WHERE job->>'status' IN ('succeeded', 'failed')"
                    " ORDER BY created_at, id LIMIT %s", (count - self.max_jobs + 1,),
                ).fetchall()
                if len(victims) < count - self.max_jobs + 1:
                    raise _capacity_error()
                c.execute("DELETE FROM analysis_jobs WHERE id = ANY(%s)", ([r["id"] for r in victims],))
            c.execute(
                "INSERT INTO analysis_jobs (id, dedupe_key, job, options, owner_id, expires_at, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (UUID(rec.job.job_id), rec.dedupe_key, Jsonb(rec.job.model_dump(mode="json")),
                 Jsonb(rec.options.model_dump(mode="json")) if rec.options is not None else None,
                 rec.owner_id, created + timedelta(seconds=self.retention_s), created),
            )

    @staticmethod
    def _save(c, rec: JobRecord) -> None:
        c.execute(
            "UPDATE analysis_jobs SET job = %s, options = %s WHERE id = %s AND expires_at > now()",
            (Jsonb(rec.job.model_dump(mode="json")),
             Jsonb(rec.options.model_dump(mode="json")) if rec.options is not None else None,
             UUID(rec.job.job_id)),
        )

    def save(self, rec: JobRecord) -> None:
        with self._pool.connection() as c:
            self._save(c, rec)

    def find_recent(self, dedupe_key: str, max_age_s: float) -> JobRecord | None:
        with self._pool.connection() as c:
            row = c.execute(
                "SELECT * FROM analysis_jobs WHERE dedupe_key = %s AND expires_at > now()"
                " AND created_at >= now() - %s ORDER BY created_at DESC LIMIT 1",
                (dedupe_key, timedelta(seconds=max_age_s)),
            ).fetchone()
        return self._record(row) if row else None

    def _cache_report(self, c, jid: UUID, pdf: bytes) -> None:
        if len(pdf) > self.max_pdf_bytes:
            return
        _advisory_lock(c, "fieldshift:analysis_jobs:pdf_capacity")
        cached = c.execute(
            "SELECT id, octet_length(report_pdf) AS bytes FROM analysis_jobs"
            " WHERE report_pdf IS NOT NULL ORDER BY created_at, id",
        ).fetchall()
        total = sum(r["bytes"] for r in cached)
        for old in cached:
            if total + len(pdf) <= self.max_pdf_bytes:
                break
            c.execute("UPDATE analysis_jobs SET report_pdf = NULL WHERE id = %s", (old["id"],))
            total -= old["bytes"]
        c.execute("UPDATE analysis_jobs SET report_pdf = %s WHERE id = %s", (pdf, jid))

    def report(self, job_id: str, render: ReportRenderer) -> bytes:
        jid = _job_id(job_id)
        if jid is None:
            raise not_found("Analysis job not found.", job_id=job_id)
        with self._pool.connection() as c:
            _advisory_lock(c, str(jid))
            row = c.execute(
                "SELECT * FROM analysis_jobs WHERE id = %s AND expires_at > clock_timestamp()", (jid,),
            ).fetchone()
            if row is None:
                raise not_found("Analysis job not found.", job_id=job_id)
            rec = self._record(row)
            if rec.report_pdf is not None:
                return rec.report_pdf
            pdf = render(rec)
            self._cache_report(c, jid, pdf)
            return pdf

    def close(self) -> None:
        self._pool.close()
