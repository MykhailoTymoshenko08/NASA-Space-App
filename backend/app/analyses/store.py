"""Job store. In-memory for the MVP (jobs are lost on restart); swap for Redis/DB behind JobStore."""

import time
from dataclasses import dataclass, field
from typing import Protocol

from app.models import AnalysisJob, AnalysisOptions

JOB_RETENTION_S = 3600


@dataclass
class JobRecord:
    job: AnalysisJob
    dedupe_key: str
    created_mono: float = field(default_factory=time.monotonic)
    # The farmer's choices, kept for the PDF report (the result itself does not echo them).
    options: AnalysisOptions | None = None
    # The rendered PDF report, made on first download: a finished job never changes.
    report_pdf: bytes | None = None


class JobStore(Protocol):
    def get(self, job_id: str) -> JobRecord | None: ...
    def put(self, rec: JobRecord) -> None: ...
    def find_recent(self, dedupe_key: str, max_age_s: float) -> JobRecord | None: ...


class InMemoryJobStore:
    def __init__(self, retention_s: float = JOB_RETENTION_S):
        self._jobs: dict[str, JobRecord] = {}
        self._by_key: dict[str, str] = {}
        self.retention_s = retention_s

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.retention_s
        for jid in [j for j, r in self._jobs.items() if r.created_mono < cutoff]:
            rec = self._jobs.pop(jid)
            if self._by_key.get(rec.dedupe_key) == jid:
                del self._by_key[rec.dedupe_key]

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def put(self, rec: JobRecord) -> None:
        self._prune()
        self._jobs[rec.job.job_id] = rec
        self._by_key[rec.dedupe_key] = rec.job.job_id

    def find_recent(self, dedupe_key: str, max_age_s: float) -> JobRecord | None:
        jid = self._by_key.get(dedupe_key)
        rec = self._jobs.get(jid) if jid else None
        if rec and time.monotonic() - rec.created_mono <= max_age_s:
            return rec
        return None
