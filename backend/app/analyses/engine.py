"""Plug-in point for the rotation model. The ML teammate replaces StubAnalysisEngine with a real one.

Contract for implementations:
- Return an `AnalysisResult` exactly as described in contract/openapi.yaml (>= 3 strategies, one with
  `is_current = true`, sorted by `score` descending, every required field present).
- Call `progress(percent, stage)` as work advances; `stage` is shown to farmers, keep it plain English.
- Raise an exception to fail the job; the job runner turns it into `status = failed`.
- `options.crop_history`, when given by the farmer, overrides `selection.crop_history` (mapped data).
"""

from collections.abc import Callable
from typing import Protocol

from app.models import AnalysisOptions, AnalysisResult, FieldSelection, Snapshot

ProgressFn = Callable[[int, str], None]


class AnalysisEngine(Protocol):
    async def run(
        self,
        selection: FieldSelection,
        options: AnalysisOptions,
        snapshot: Snapshot,
        progress: ProgressFn,
    ) -> AnalysisResult: ...
