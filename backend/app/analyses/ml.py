"""Translate the backend analysis contract at the stateless ML service boundary.

The existing UI receives AnalysisResult; ml_analysis preserves the complete upstream JSON.
Only the five criteria actually scored by ML appear in score_breakdown. Monthly vulnerability
is a climate normal, not historical observations, so it is not relabelled as a time series.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.analyses.engine import ProgressFn
from app.core.errors import ApiException, ErrorCode
from app.models import (
    AnalysisOptions,
    AnalysisResult,
    BoundaryType,
    Criterion,
    CriterionScore,
    DatasetRef,
    Evidence,
    FieldSelection,
    Priority,
    Quality,
    RotationRole,
    RotationSeason,
    Snapshot,
    Strategy,
)
from app.profitability.rotation import compare_budgets, estimate_rotation_budget

# Names stored by prepare_csb.py come from scripts/cdl_codes.json. Retain CDL codes for
# fallow and double crops: reducing these to an arbitrary slug changes rotation detection.
CROPS = {
    "corn": ("corn", 1), "soybeans": ("soybean", 5), "soybean": ("soybean", 5),
    "sorghum": ("sorghum", 4), "winter wheat": ("winter_wheat", 24),
    "oats": ("oats", 28), "barley": ("barley", 21), "alfalfa": ("alfalfa", 36),
    "rye": ("cereal_rye", 27), "cereal rye": ("cereal_rye", 27),
    "fallow": ("fallow", 61), "fallow/idle cropland": ("fallow", 61),
}
DOUBLE_CROPS = {
    "winwht/soybeans": 26, "winwht/corn": 225, "oats/corn": 226, "triticale/corn": 228,
    "lettuce/durum wht": 230, "lettuce/cantaloupe": 231, "lettuce/cotton": 232,
    "lettuce/barley": 233, "durum wht/sorghum": 234, "barley/sorghum": 235,
    "winwht/sorghum": 236, "barley/corn": 237, "winwht/cotton": 238,
    "soybeans/cotton": 239, "soybeans/oats": 240, "corn/soybeans": 241, "barley/soybeans": 254,
}
CROP_NAMES = {
    "corn": "Corn", "soybean": "Soybeans", "winter_wheat": "Winter Wheat",
    "sorghum": "Sorghum", "oats": "Oats", "barley": "Barley", "alfalfa": "Alfalfa",
    "cereal_rye": "Cereal rye", "hairy_vetch": "Hairy vetch", "clover": "Clover",
    "fallow": "Fallow", "other": "Other crops", "unknown": "Unknown crop",
}
PRIORITIES = {
    Priority.water_conservation: "water", Priority.extra_income: "income",
    Priority.soil_health: "soil_health", Priority.erosion_control: "erosion",
    Priority.nitrogen_fixing: "nitrogen", Priority.low_input_cost: "income",
}
CRITERIA = {
    "water": Criterion.water_use, "soil_health": Criterion.soil_health,
    "nitrogen": Criterion.nitrogen, "erosion": Criterion.erosion, "income": Criterion.income,
}
PROVIDERS = {
    "csb": "USDA NASS", "ssurgo": "USDA NRCS", "power": "NASA",
    "landsat_ndvi": "NASA / USGS", "smap": "NASA", "nasadem": "NASA",
}

Score = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]


class MLScores(BaseModel):
    water: Score
    soil_health: Score
    nitrogen: Score
    erosion: Score
    income: Score
    overall: Score


class MLSeason(BaseModel):
    year: int = Field(ge=1, le=5)
    season: Literal["main", "cover"]
    crop: str


class MLEvidence(BaseModel):
    text: str
    source_ids: list[str]


class MLSource(BaseModel):
    id: str
    name: str
    variable: str
    resolution: str
    period: str


class MLStrategy(BaseModel):
    id: str
    is_current: bool
    name: str
    sequence: list[MLSeason] = Field(min_length=1)
    scores: MLScores
    why: str
    evidence: list[MLEvidence]
    benefits: list[str]
    risks: list[str]
    data_gaps: list[str]
    check_with_agronomist: list[str]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class MLResponse(BaseModel):
    request_id: str
    field_id: str
    generated_at: datetime
    model_version: str
    status: Literal["ok", "partial"]
    strategies: list[MLStrategy] = Field(min_length=1)
    sources: list[MLSource]
    warnings: list[str]
    disclaimer: str


def ml_request(selection: FieldSelection, options: AnalysisOptions) -> dict:
    """Use the edition-free CSBID and explicit WGS84 coordinates; farmer history takes precedence."""
    field_id = selection.field_id
    if field_id and field_id.startswith("csb") and "_" in field_id:
        field_id = field_id.split("_", 1)[1]
    field = {
        "field_id": field_id or f"point:{selection.anchor.lat:.6f},{selection.anchor.lon:.6f}",
        "centroid": selection.anchor.model_dump(),
        "geometry": selection.geometry.model_dump(),
        "admin": {
            "country": "US", "state": selection.county.state_postal,
            "state_fips": selection.county.fips[:2], "county_fips": selection.county.fips,
        },
    }
    if selection.area_ha is not None and selection.area_ha > 0:
        field["area_ha"] = selection.area_ha
    history = options.crop_history if options.crop_history is not None else selection.crop_history
    if history:
        rows = []
        for item in sorted(history, key=lambda h: h.year):
            name = item.crop.strip().lower().replace("_", " ")
            slug, code = CROPS.get(name, (item.crop.strip(), None))
            if name.startswith("dbl crop "):
                code = DOUBLE_CROPS.get(name.removeprefix("dbl crop "))
            row = {"year": item.year, "crop": slug}
            if code is not None:
                row["cdl_code"] = code
            rows.append(row)
        field["crop_history"] = rows
    weights = dict.fromkeys(CRITERIA, 0.5)
    for priority in options.priorities:
        weights[PRIORITIES[priority]] = 1.0
    return {
        "request_id": str(uuid.uuid4()), "field": field, "priorities": weights,
        "options": {"n_strategies": 3, "language": "en", "horizon_years": options.horizon_years},
    }


def _role(season: MLSeason) -> RotationRole:
    if season.season == "cover":
        return RotationRole.cover_crop
    if season.crop == "fallow":
        return RotationRole.fallow
    if season.crop == "alfalfa":
        return RotationRole.forage
    if season.crop in {"soybean", "clover", "hairy_vetch"}:
        return RotationRole.nitrogen_fixer
    return RotationRole.cash_crop


def _result(
    raw: dict, selection: FieldSelection, snapshot: Snapshot, options: AnalysisOptions,
) -> AnalysisResult:
    data = MLResponse.model_validate(raw)
    if sum(s.is_current for s in data.strategies) != 1:
        raise ValueError("ML must return exactly one current rotation")
    if len({s.id for s in data.strategies}) != len(data.strategies):
        raise ValueError("ML strategy IDs must be unique")
    sources = {
        s.id: DatasetRef(dataset=s.name, provider=PROVIDERS.get(s.id, "ML service"), coverage_period=s.period)
        for s in data.sources
    }
    strategies = []
    history = options.crop_history if options.crop_history is not None else selection.crop_history
    previous = max(history, key=lambda h: h.year).crop if history else None
    for s in data.strategies:
        evidence = []
        for item in s.evidence:
            if any(ref not in sources for ref in item.source_ids):
                raise ValueError("ML evidence refers to an unknown source")
            evidence.append(Evidence(
                statement=item.text, source=sources[item.source_ids[0]] if item.source_ids else None,
            ))
        strategies.append(Strategy(
            id=s.id, name=s.name, is_current=s.is_current,
            rotation=[RotationSeason(
                season_index=i, crop=CROP_NAMES.get(season.crop, season.crop.replace("_", " ")),
                role=_role(season),
            ) for i, season in enumerate(s.sequence)],
            score=s.scores.overall,
            score_breakdown=[CriterionScore(criterion=c, score=getattr(s.scores, key))
                             for key, c in CRITERIA.items()],
            confidence="high" if s.confidence >= 0.8 else "medium" if s.confidence >= 0.5 else "low",
            summary=s.why, benefits=s.benefits, risks=s.risks, evidence=evidence,
            information_gaps=[*s.data_gaps, *(f"Check with a local agronomist: {x}"
                                            for x in s.check_with_agronomist)],
            needs_local_review=True,
            budget=estimate_rotation_budget(
                [season.model_dump() for season in s.sequence], selection.county.state_postal,
                selection.area_ha, options.budget, previous_crop=previous,
                horizon_years=options.horizon_years,
            ),
        ))
    current_budget = next(s.budget for s in strategies if s.is_current)
    compare_budgets([s.budget for s in strategies], current_budget)
    datasets = {(s.dataset, s.provider): s for s in sources.values()}
    for m in snapshot.metrics:
        if m.quality != Quality.unavailable:
            datasets.setdefault((m.source.dataset, m.source.provider), DatasetRef(
                dataset=m.source.dataset, provider=m.source.provider, url=m.source.url,
                resolution_m=m.resolution_m,
            ))
    warnings = [*data.warnings, "Income is a relative 0-100 index, not a profit estimate."]
    if "mock" in data.model_version.lower():
        warnings.append("ML mock mode: these are demonstration results, not real model predictions.")
    if selection.boundary_type == BoundaryType.buffered_point:
        warnings.append(f"No estimated field area here: results use a {selection.buffer_m:g} m circle.")
    return AnalysisResult(
        selection=selection, generated_at=data.generated_at, model_version=data.model_version,
        current_conditions=snapshot.metrics, strategies=sorted(strategies, key=lambda s: -s.score),
        datasets_used=list(datasets.values()), warnings=warnings, disclaimer=data.disclaimer, ml_analysis=raw,
    )


class MLAnalysisEngine:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def run(
        self, selection: FieldSelection, options: AnalysisOptions, snapshot: Snapshot, progress: ProgressFn,
    ) -> AnalysisResult:
        payload = ml_request(selection, options)
        progress(25, "Evaluating crops and rotation options")
        try:
            response = await self.client.post("ml/v1/analyze", json=payload)
        except httpx.RequestError as exc:
            raise ApiException(
                ErrorCode.UPSTREAM_DATA_UNAVAILABLE,
                "The crop analysis service is unavailable. Please try again in a minute.",
                {"retry_after_s": 60},
            ) from exc
        if response.status_code != 200:
            raise _upstream_error(response)
        try:
            raw = response.json()
            if raw["field_id"] != payload["field"]["field_id"] or raw["request_id"] != payload["request_id"]:
                raise ValueError("ML response does not match the request")
            result = _result(raw, selection, snapshot, options)
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            raise ApiException(
                ErrorCode.UPSTREAM_DATA_UNAVAILABLE,
                "The crop analysis service returned an invalid result. Please try again.",
            ) from exc
        progress(95, "Preparing your results")
        return result


def _upstream_error(response: httpx.Response) -> ApiException:
    try:
        error = response.json()["error"]
        code = error["code"]
        message = error["message"]
        details = error.get("details")
        if not isinstance(message, str) or not isinstance(details, (dict, type(None))):
            raise ValueError("Invalid ML error")
    except (ValueError, KeyError, TypeError):
        code, message, details = "", "The crop analysis service is unavailable. Please try again.", None
    if response.status_code == 422 and code == "INVALID_INPUT":
        return ApiException(ErrorCode.VALIDATION_ERROR, message, details)
    if response.status_code == 404 and code == "OUT_OF_COVERAGE":
        return ApiException(ErrorCode.OUTSIDE_COVERAGE, message, details)
    # Infrastructure/internal errors must not expose a traceback or proxy response to the farmer.
    details = {"retry_after_s": 60} if response.status_code in {429, 503} else None
    return ApiException(
        ErrorCode.UPSTREAM_DATA_UNAVAILABLE,
        "The crop analysis service could not complete this analysis. Please try again in a minute.", details,
    )
