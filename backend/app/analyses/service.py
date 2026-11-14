"""Analysis job lifecycle: create, dedupe, run in the background, report progress."""

import asyncio
import json
import logging
import random
import uuid
from datetime import UTC, datetime

from app.analyses.engine import AnalysisEngine
from app.analyses.store import JobRecord, JobStore
from app.core.errors import ErrorCode
from app.models import (
    AnalysisJob,
    AnalysisOptions,
    ApiError,
    FieldSelection,
    JobStatus,
    Progress,
)
from app.snapshots.service import SnapshotService

log = logging.getLogger(__name__)


class StubFailure(RuntimeError):
    """Raised on purpose when STUB_FAIL_RATE triggers, so the frontend can test `failed`."""


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def dedupe_key(selection: FieldSelection, options: AnalysisOptions) -> str:
    where = selection.field_id or f"{selection.anchor.lat:.5f},{selection.anchor.lon:.5f}"
    opts = json.dumps(options.model_dump(mode="json"), sort_keys=True)
    return f"{where}|{opts}"


class AnalysisService:
    def __init__(
        self,
        store: JobStore,
        engine: AnalysisEngine,
        snapshots: SnapshotService,
        dedupe_ttl_s: float = 600,
        fail_rate: float = 0.0,
    ):
        self.store = store
        self.engine = engine
        self.snapshots = snapshots
        self.dedupe_ttl_s = dedupe_ttl_s
        self.fail_rate = fail_rate
        self._tasks: set[asyncio.Task] = set()

    def create(self, selection: FieldSelection, options: AnalysisOptions) -> AnalysisJob:
        key = dedupe_key(selection, options)
        existing = self.store.find_recent(key, self.dedupe_ttl_s)
        if existing and existing.job.status != JobStatus.failed:
            return existing.job

        job = AnalysisJob(
            job_id=str(uuid.uuid4()),
            status=JobStatus.queued,
            created_at=_now(),
            progress=Progress(percent=0, stage="Waiting to start"),
        )
        self.store.put(JobRecord(job=job, dedupe_key=key))
        task = asyncio.create_task(self._run(job, selection, options))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def get(self, job_id: str) -> AnalysisJob | None:
        rec = self.store.get(job_id)
        return rec.job if rec else None

    async def _run(self, job: AnalysisJob, selection: FieldSelection, options: AnalysisOptions) -> None:
        def progress(percent: int, stage: str) -> None:
            # Never go backwards, never claim 100 % before the result is stored.
            job.progress = Progress(percent=max(job.progress.percent, min(int(percent), 99)), stage=stage)

        try:
            job.status = JobStatus.running
            progress(2, "Starting analysis")
            snapshot = await self.snapshots.snapshot(selection)
            if self.fail_rate and random.random() < self.fail_rate:
                await asyncio.sleep(0)
                raise StubFailure("STUB_FAIL_RATE triggered")
            result = await self.engine.run(selection, options, snapshot, progress)
            job.result = result
            job.progress = Progress(percent=100, stage="Done")
            job.status = JobStatus.succeeded
        except Exception as e:  # noqa: BLE001 - a failed job is reported, never raised
            log.warning("analysis %s failed: %r", job.job_id, e)
            job.error = ApiError(
                code=ErrorCode.INTERNAL_ERROR,
                message="The analysis could not be completed. Please try again.",
                details={"reason": "simulated_failure"} if isinstance(e, StubFailure) else None,
            )
            job.status = JobStatus.failed
        finally:
            job.finished_at = _now()


def job_json(job: AnalysisJob) -> dict:
    """`result` only when succeeded and `error` only when failed (contract), so drop them otherwise."""
    d = job.model_dump(mode="json")
    if job.status != JobStatus.succeeded:
        d.pop("result", None)
    if job.status != JobStatus.failed:
        d.pop("error", None)
    if d.get("error") and d["error"].get("details") is None:
        d["error"].pop("details")
    if d.get("error") and d["error"].get("request_id") is None:
        d["error"].pop("request_id")
    return d
