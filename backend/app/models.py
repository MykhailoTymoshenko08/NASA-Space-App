"""Pydantic models mirroring `contract/openapi.yaml` (v0.4.0).

Keep names and enums identical to the contract. The contract tests validate real responses
against the YAML, so drift is caught there.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.errors import ErrorCode

BBox = Annotated[list[float], Field(min_length=4, max_length=4)]
StateFips = Annotated[str, Field(pattern=r"^[0-9]{2}$")]
CountyFips = Annotated[str, Field(pattern=r"^[0-9]{5}$")]


class LatLon(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class GeoJSONPolygon(BaseModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]


class GeoJSONPoint(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: list[float] = Field(min_length=2, max_length=2)


# ---------- geo ----------
class State(BaseModel):
    fips: str
    name: str
    postal: str
    bbox: list[float]


class County(BaseModel):
    fips: str
    name: str
    state_fips: str
    state_postal: str
    bbox: list[float]
    centroid: LatLon
    has_field_coverage: bool


class FieldTilesInfo(BaseModel):
    format: Literal["pmtiles"] = "pmtiles"
    unit: Literal["estimated_csb"] = "estimated_csb"
    min_zoom: int
    max_zoom: int
    url_template: str
    regions: list[dict[str, Any]]


class FieldBoundarySource(BaseModel):
    name: str
    edition: str
    boundary_type: Literal["estimated_csb"] = "estimated_csb"
    attribution: str | None = None


class Coverage(BaseModel):
    bounds: list[float]
    supported_states: list[str]
    field_data_version: str
    field_boundary_source: FieldBoundarySource
    field_tiles: FieldTilesInfo


# ---------- selection ----------
class SelectionSource(StrEnum):
    landing_map_click = "landing_map_click"
    county_pick = "county_pick"
    location_link = "location_link"
    coordinates = "coordinates"
    map_click = "map_click"


class BoundaryType(StrEnum):
    estimated_csb = "estimated_csb"
    buffered_point = "buffered_point"


class ResolvedBy(StrEnum):
    field_polygon = "field_polygon"
    snapped_point = "snapped_point"
    buffered_point = "buffered_point"


class FieldIdRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_id: str = Field(min_length=1, max_length=64)


class PointRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    point: LatLon


SelectionRef = FieldIdRef | PointRef


class CountyRef(BaseModel):
    fips: str
    name: str
    state_postal: str


class CropYear(BaseModel):
    year: int = Field(ge=1990, le=2100)
    crop: str


class FieldSelection(BaseModel):
    field_id: str | None
    anchor: LatLon
    geometry: GeoJSONPolygon
    bbox: list[float]
    resolved_by: ResolvedBy
    boundary_type: BoundaryType
    snap_distance_m: float | None = None
    buffer_m: float | None = None
    area_ha: float | None
    # From CSB: latest mapped crop and per-year history (newest first). Null / [] for buffered points.
    crop_class: str | None = None
    county: CountyRef
    source: SelectionSource
    crop_history: list[CropYear] = Field(default_factory=list)


class FieldResolveRequest(BaseModel):
    point: LatLon
    snap_radius_m: float = Field(default=300, ge=0, le=2000)
    source: SelectionSource | None = None


class LocationResolveRequest(BaseModel):
    input: str = Field(min_length=3, max_length=2048)


class InputKind(StrEnum):
    plain_coordinates = "plain_coordinates"
    google_maps_url = "google_maps_url"
    apple_maps_url = "apple_maps_url"


class ResolvedLocation(BaseModel):
    input_kind: InputKind
    point: LatLon
    selection: FieldSelection


# ---------- metrics ----------
class MetricCategory(StrEnum):
    moisture = "moisture"
    atmosphere = "atmosphere"
    temperature = "temperature"
    precipitation = "precipitation"
    soil = "soil"
    terrain = "terrain"
    vegetation = "vegetation"


class Quality(StrEnum):
    measured = "measured"
    modeled = "modeled"
    estimated = "estimated"
    unavailable = "unavailable"


class MetricSource(BaseModel):
    dataset: str
    provider: str
    url: str | None = None


class Period(BaseModel):
    start: date
    end: date


class Metric(BaseModel):
    key: str
    label: str
    category: MetricCategory
    value: float | str | None
    unit: str
    as_of: date | None = None
    period: Period | None = None
    quality: Quality
    unavailable_reason: str | None = None
    source: MetricSource
    resolution_m: float | None
    note: str | None = None


class Snapshot(BaseModel):
    selection: FieldSelection
    generated_at: datetime
    cached: bool
    metrics: list[Metric]


class SnapshotRequest(BaseModel):
    selection: SelectionRef


class FieldInfo(BaseModel):
    point: LatLon
    generated_at: datetime
    cached: bool
    metrics: list[Metric]


# ---------- analysis ----------
class Priority(StrEnum):
    water_conservation = "water_conservation"
    extra_income = "extra_income"
    soil_health = "soil_health"
    erosion_control = "erosion_control"
    low_input_cost = "low_input_cost"
    nitrogen_fixing = "nitrogen_fixing"


class AnalysisOptions(BaseModel):
    priorities: list[Priority] = Field(default_factory=list, max_length=6)
    crop_history: list[CropYear] | None = Field(default=None, max_length=10)
    horizon_years: int = Field(default=3, ge=1, le=5)


class AnalysisRequest(BaseModel):
    selection: SelectionRef
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class Progress(BaseModel):
    percent: int = Field(ge=0, le=100)
    stage: str


class ApiError(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class DatasetRef(BaseModel):
    dataset: str
    provider: str
    url: str | None = None
    resolution_m: float | None = None
    coverage_period: str | None = None


class TimeSeriesPoint(BaseModel):
    t: date
    v: float | None


class TimeSeries(BaseModel):
    key: str
    label: str
    unit: str
    source: DatasetRef | None = Field(default=None, exclude_if=lambda v: v is None)
    points: list[TimeSeriesPoint]


class RotationRole(StrEnum):
    cash_crop = "cash_crop"
    cover_crop = "cover_crop"
    nitrogen_fixer = "nitrogen_fixer"
    forage = "forage"
    fallow = "fallow"


class RotationSeason(BaseModel):
    season_index: int = Field(ge=0)
    crop: str
    role: RotationRole


class Criterion(StrEnum):
    water_use = "water_use"
    soil_health = "soil_health"
    erosion = "erosion"
    nitrogen = "nitrogen"
    pest_cycle = "pest_cycle"
    income = "income"
    climate_risk = "climate_risk"


class CriterionScore(BaseModel):
    criterion: Criterion
    score: float = Field(ge=0, le=100)


class Evidence(BaseModel):
    statement: str
    metric_key: str | None = None
    # Contract: `source` is an object, not nullable, so omit it rather than send null.
    source: DatasetRef | None = Field(default=None, exclude_if=lambda v: v is None)


class Strategy(BaseModel):
    id: str
    name: str
    is_current: bool
    rotation: list[RotationSeason]
    score: float = Field(ge=0, le=100)
    score_breakdown: list[CriterionScore]
    confidence: Literal["low", "medium", "high"]
    summary: str
    benefits: list[str]
    risks: list[str]
    evidence: list[Evidence]
    information_gaps: list[str]
    needs_local_review: bool


class AnalysisResult(BaseModel):
    selection: FieldSelection
    generated_at: datetime
    model_version: str
    current_conditions: list[Metric]
    time_series: list[TimeSeries] = Field(default_factory=list)
    strategies: list[Strategy] = Field(min_length=3)
    datasets_used: list[DatasetRef]
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str


class AnalysisJob(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    finished_at: datetime | None = None
    progress: Progress
    result: AnalysisResult | None = None
    error: ApiError | None = None


# ---------- profitability ----------
class ProfitCrop(StrEnum):
    corn = "Corn"
    soybeans = "Soybeans"
    winter_wheat = "Winter Wheat"


class ProfitState(StrEnum):
    IA = "IA"
    IL = "IL"
    NE = "NE"


class CostOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")
    land_rent_per_acre: float | None = Field(default=None, ge=0, le=5000)
    total_cost_per_acre: float | None = Field(default=None, ge=0, le=10000)


class ProfitEstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    crop: ProfitCrop
    state: ProfitState
    predicted_yield: float | None = Field(default=None, gt=0, le=1000)
    previous_crop: str | None = Field(default=None, max_length=100)
    cost_overrides: CostOverrides = Field(default_factory=CostOverrides)


class ProfitScenario(BaseModel):
    price: float
    revenue_per_acre: float
    cost_per_acre: float
    profit_per_acre: float


class ProfitCostItem(BaseModel):
    key: Literal["seed", "fertilizer", "chemicals", "other_operating", "land_rent", "total"]
    label: str
    amount_per_acre: float
    source: Literal["baseline", "farmer", "baseline_with_nitrogen_credit"]


class ProfitScenarios(BaseModel):
    low: ProfitScenario
    base: ProfitScenario
    high: ProfitScenario


class ProfitBaselineInfo(BaseModel):
    version: str
    is_placeholder: bool


class ProfitEstimate(BaseModel):
    crop: ProfitCrop
    state: ProfitState
    yield_per_acre: float
    yield_unit: str
    yield_source: Literal["model", "baseline_default"]
    costs: list[ProfitCostItem]
    scenarios: ProfitScenarios
    assumptions: list[str]
    baseline: ProfitBaselineInfo


# --- Auth -------------------------------------------------------------------------------------------

PASSWORD_MIN = 8
PASSWORD_MAX = 128


def _normalize_email(v: Any) -> Any:
    # Runs before EmailStr: accounts are case-insensitive, so the whole address is stored lowercase.
    return v.strip().lower() if isinstance(v, str) else v


Email = Annotated[EmailStr, BeforeValidator(_normalize_email), Field(max_length=254)]


def _strong_password(v: str) -> str:
    if not any(ch.isalpha() for ch in v) or not any(ch.isdigit() for ch in v):
        raise ValueError("Password must contain at least one letter and one digit")
    return v


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)

    @field_validator("password")
    @classmethod
    def _password_rules(cls, v: str) -> str:
        return _strong_password(v)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email
    # No strength rules on login: a wrong password just fails with 401.
    password: str = Field(min_length=1, max_length=PASSWORD_MAX)


class NewPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)

    @field_validator("new_password")
    @classmethod
    def _password_rules(cls, v: str) -> str:
        return _strong_password(v)


class ChangePasswordRequest(NewPasswordRequest):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX)


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email


class ResetPasswordRequest(NewPasswordRequest):
    token: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: UUID
    email: str
    created_at: datetime


class AuthTokens(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds
    user: UserOut


# --- Saved fields -----------------------------------------------------------------------------------

SAVED_FIELD_NAME_MAX = 100
SavedFieldName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=SAVED_FIELD_NAME_MAX)
]
SavedGeometry = Annotated[GeoJSONPoint | GeoJSONPolygon, Field(discriminator="type")]


class SavedCropYear(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int = Field(ge=1990, le=2100)
    crop: str = Field(min_length=1, max_length=64)


class SavedFieldCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: SavedFieldName
    geometry: SavedGeometry
    # CSB id when the farmer picked a mapped field; null for a buffered point or a drawn shape.
    field_id: str | None = Field(default=None, min_length=1, max_length=64)
    crop_history: list[SavedCropYear] | None = Field(default=None, max_length=10)


class SavedFieldUpdate(BaseModel):
    """Partial update. Omitted keys stay as they are; `crop_history: null` clears it."""

    model_config = ConfigDict(extra="forbid")
    name: SavedFieldName | None = None
    crop_history: list[SavedCropYear] | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def _name_not_null(self) -> "SavedFieldUpdate":
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        if not self.model_fields_set:
            raise ValueError("Give at least one of name, crop_history")
        return self


class SavedField(BaseModel):
    id: UUID
    name: str
    field_id: str | None
    geometry: SavedGeometry
    centroid: LatLon
    area_ha: float | None
    state: Literal["IA", "IL", "NE"]
    crop_history: list[SavedCropYear] | None
    info: FieldInfo | None
    info_fetched_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SavedFieldList(BaseModel):
    items: list[SavedField]
    limit: int
