"""StubAnalysisEngine: placeholder results with the exact AnalysisResult shape.

Deterministic per field (seeded), clearly labelled as a demo, never presented as real science.
"""

import asyncio
import hashlib
import random
from datetime import UTC, datetime

from app.analyses.engine import ProgressFn
from app.models import (
    AnalysisOptions,
    AnalysisResult,
    Criterion,
    CriterionScore,
    CropYear,
    DatasetRef,
    Evidence,
    FieldSelection,
    Metric,
    Priority,
    Quality,
    ResolvedBy,
    RotationRole,
    RotationSeason,
    Snapshot,
    Strategy,
)

MODEL_VERSION = "stub-0"
DEMO_WARNING = "Demo results: placeholder strategies, real model not connected yet."
DISCLAIMER = (
    "Field Shift is a decision-support tool. It summarises public NASA and USDA data and suggests "
    "options to discuss; it does not replace advice from your local agronomist, extension office, "
    "or crop adviser, who know your soil, markets, equipment and programs. Check any change locally "
    "before acting on it."
)
STAGES = [
    (10, "Reading field boundary and crop history"),
    (30, "Fetching soil moisture history"),
    (55, "Checking soil and weather conditions"),
    (80, "Comparing rotation options"),
    (95, "Preparing your results"),
]

# Placeholder rotation catalogue: (id, name, [(crop, role)], criteria tilt).
CATALOGUE = [
    ("strat_corn_soy", "Corn / soybean rotation",
     [("Corn", RotationRole.cash_crop), ("Soybeans", RotationRole.nitrogen_fixer)],
     {Criterion.income: 10, Criterion.nitrogen: 5}),
    ("strat_corn_soy_rye", "Corn / soybean with winter cereal rye cover",
     [("Corn", RotationRole.cash_crop), ("Cereal rye", RotationRole.cover_crop),
      ("Soybeans", RotationRole.nitrogen_fixer), ("Cereal rye", RotationRole.cover_crop)],
     {Criterion.erosion: 15, Criterion.soil_health: 10, Criterion.water_use: 5}),
    ("strat_corn_soy_oats_clover", "Corn / soybean / oats underseeded with red clover",
     [("Corn", RotationRole.cash_crop), ("Soybeans", RotationRole.nitrogen_fixer),
      ("Oats", RotationRole.cash_crop), ("Red clover", RotationRole.nitrogen_fixer)],
     {Criterion.nitrogen: 15, Criterion.pest_cycle: 15, Criterion.soil_health: 10}),
    ("strat_soy_wheat_alfalfa", "Soybean / winter wheat / alfalfa hay",
     [("Soybeans", RotationRole.nitrogen_fixer), ("Winter wheat", RotationRole.cash_crop),
      ("Alfalfa", RotationRole.forage)],
     {Criterion.erosion: 10, Criterion.water_use: 10, Criterion.climate_risk: 5}),
]

PRIORITY_CRITERIA = {
    Priority.water_conservation: Criterion.water_use,
    Priority.extra_income: Criterion.income,
    Priority.soil_health: Criterion.soil_health,
    Priority.erosion_control: Criterion.erosion,
    Priority.low_input_cost: Criterion.income,
    Priority.nitrogen_fixing: Criterion.nitrogen,
}

FIXERS = ("soy", "alfalfa", "clover", "pea", "bean", "vetch")
FORAGE = ("grass", "pasture", "hay", "alfalfa")
COVERS = ("rye", "cover")


def role_for(crop: str) -> RotationRole:
    c = crop.lower()
    if "fallow" in c or "idle" in c:
        return RotationRole.fallow
    if any(k in c for k in FORAGE) and "alfalfa" not in c:
        return RotationRole.forage
    if any(k in c for k in FIXERS):
        return RotationRole.nitrogen_fixer
    if any(k in c for k in COVERS):
        return RotationRole.cover_crop
    return RotationRole.cash_crop


def seed_for(selection: FieldSelection) -> int:
    key = selection.field_id or f"{selection.anchor.lat:.4f},{selection.anchor.lon:.4f}"
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")


def _history(selection: FieldSelection, options: AnalysisOptions) -> list[CropYear]:
    hist = options.crop_history if options.crop_history else selection.crop_history
    return sorted(hist, key=lambda h: h.year, reverse=True)


def _baseline(selection: FieldSelection, options: AnalysisOptions) -> tuple[str, list[RotationSeason], str]:
    hist = _history(selection, options)
    if hist:
        crops = [h.crop for h in reversed(hist[:4])]  # oldest -> newest, last 4 seasons
        # Collapse to one cycle: keep order of first appearance.
        cycle = list(dict.fromkeys(crops))
        name = "Continue current rotation: " + " / ".join(cycle)
        basis = f"crop history {hist[-1].year}-{hist[0].year}"
    elif selection.crop_class:
        cycle = [selection.crop_class]
        name = f"Continue current practice: {selection.crop_class}"
        basis = "the latest mapped crop (USDA Crop Sequence Boundaries)"
    else:
        cycle = ["Current crop (unknown)"]
        name = "Continue current practice"
        basis = "no crop data for this spot"
    rotation = [RotationSeason(season_index=i, crop=c, role=role_for(c)) for i, c in enumerate(cycle)]
    return name, rotation, basis


def _breakdown(rng: random.Random, tilt: dict[Criterion, int]) -> list[CriterionScore]:
    return [
        CriterionScore(criterion=c, score=float(min(100, max(0, rng.randint(35, 70) + tilt.get(c, 0)))))
        for c in Criterion
    ]


def _score(breakdown: list[CriterionScore], priorities: list[Priority]) -> float:
    weights = {c: 1.0 for c in Criterion}
    for p in priorities:
        weights[PRIORITY_CRITERIA[p]] += 1.0
    total = sum(weights[b.criterion] * b.score for b in breakdown)
    return round(total / sum(weights.values()), 1)


def _available(metrics: list[Metric]) -> list[Metric]:
    return [m for m in metrics if m.quality != Quality.unavailable]


def _dataset(m: Metric) -> DatasetRef:
    return DatasetRef(dataset=m.source.dataset, provider=m.source.provider, url=m.source.url,
                      resolution_m=m.resolution_m)


def _evidence(rng: random.Random, metrics: list[Metric]) -> list[Evidence]:
    avail = _available(metrics)
    picks = rng.sample(avail, k=min(2, len(avail))) if avail else []
    ev = [
        Evidence(
            statement=(f"Placeholder: the real model will weigh {m.label.lower()} "
                       f"({m.value} {m.unit}) for this option."),
            metric_key=m.key,
            source=_dataset(m),
        )
        for m in picks
    ]
    ev.append(Evidence(statement="Placeholder: no agronomic model was run (demo stub).",
                       metric_key=None))
    return ev


def _gaps(selection: FieldSelection, metrics: list[Metric]) -> list[str]:
    gaps = ["Demo stub: no rotation model has evaluated this field yet."]
    missing = [m.label for m in metrics if m.quality == Quality.unavailable]
    if missing:
        gaps.append("Data not available right now: " + ", ".join(missing) + ".")
    if not selection.crop_history:
        gaps.append("No multi-year crop history for this field; enter yours for a better baseline.")
    gaps.append("Markets, equipment, labour and farm program rules are not considered.")
    return gaps


class StubAnalysisEngine:
    def __init__(self, duration_s: float = 6.0):
        self.duration_s = duration_s

    async def run(
        self,
        selection: FieldSelection,
        options: AnalysisOptions,
        snapshot: Snapshot,
        progress: ProgressFn,
    ) -> AnalysisResult:
        rng = random.Random(seed_for(selection))
        step = self.duration_s / len(STAGES)
        for pct, stage in STAGES:
            progress(pct, stage)
            await asyncio.sleep(step)

        metrics = snapshot.metrics
        base_name, base_rot, basis = _baseline(selection, options)
        strategies: list[Strategy] = []

        bd = _breakdown(rng, {})
        strategies.append(Strategy(
            id="strat_current",
            name=base_name,
            is_current=True,
            rotation=base_rot,
            score=_score(bd, options.priorities),
            score_breakdown=bd,
            confidence="low",
            summary=f"Your current practice, based on {basis}. Shown as the baseline to compare against.",
            benefits=["No change in equipment, inputs or marketing.",
                      "Placeholder: real benefits will come from the model."],
            risks=["Placeholder: real risks will come from the model."],
            evidence=_evidence(rng, metrics),
            information_gaps=_gaps(selection, metrics),
            needs_local_review=True,
        ))

        candidates = [c for c in CATALOGUE if c[2] != [(s.crop, s.role) for s in base_rot]]
        for sid, name, seasons, tilt in candidates[:3]:
            bd = _breakdown(rng, tilt)
            rotation = []
            for i in range(max(len(seasons), 1)):
                crop, role = seasons[i % len(seasons)]
                rotation.append(RotationSeason(season_index=i, crop=crop, role=role))
            strategies.append(Strategy(
                id=sid,
                name=name,
                is_current=False,
                rotation=rotation,
                score=_score(bd, options.priorities),
                score_breakdown=bd,
                confidence="low",
                summary=f"Placeholder option: {name.lower()}. Scores are demo values, not advice.",
                benefits=["Placeholder: example benefit text (demo)."],
                risks=["Placeholder: example risk text (demo)."],
                evidence=_evidence(rng, metrics),
                information_gaps=_gaps(selection, metrics),
                needs_local_review=True,
            ))

        strategies.sort(key=lambda s: (-s.score, s.id))

        seen: dict[str, DatasetRef] = {}
        for m in _available(metrics):
            seen.setdefault(m.source.dataset, _dataset(m))

        warnings = [DEMO_WARNING]
        if selection.resolved_by == ResolvedBy.buffered_point:
            warnings.append("No mapped field here: results use a 500 m circle around your point.")
        if any(m.resolution_m and m.resolution_m > 10_000 for m in _available(metrics)):
            warnings.append("Weather and soil wetness come from ~55 km grid cells, much larger than a field.")

        progress(100, "Done")
        return AnalysisResult(
            selection=selection,
            generated_at=datetime.now(UTC).replace(microsecond=0),
            model_version=MODEL_VERSION,
            current_conditions=metrics,
            time_series=[],
            strategies=strategies,
            datasets_used=list(seen.values()),
            warnings=warnings,
            disclaimer=DISCLAIMER,
        )
