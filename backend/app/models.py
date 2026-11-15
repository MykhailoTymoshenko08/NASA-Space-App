"""Pydantic models mirroring `contract/openapi.yaml` (v0.14.0).

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


class BudgetRevenueInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    low: float = Field(ge=0, le=100000, allow_inf_nan=False)
    base: float = Field(ge=0, le=100000, allow_inf_nan=False)
    high: float = Field(ge=0, le=100000, allow_inf_nan=False)

    @model_validator(mode="after")
    def _ordered(self) -> "BudgetRevenueInput":
        if not self.low <= self.base <= self.high:
            raise ValueError("Revenue scenarios must satisfy low <= base <= high")
        return self


class CropBudgetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    crop: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*(\+[a-z][a-z0-9_]*)?$")
    revenue_per_acre: BudgetRevenueInput
    production_cost_per_acre: float = Field(ge=0, le=10000, allow_inf_nan=False)


class RotationBudgetOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    land_rent_per_acre: float | None = Field(default=None, ge=0, le=5000, allow_inf_nan=False)
    cover_cost_per_acre: float | None = Field(default=None, ge=0, le=2000, allow_inf_nan=False)
    crop_overrides: list[CropBudgetInput] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def _unique_crops(self) -> "RotationBudgetOptions":
        crops = [x.crop for x in self.crop_overrides]
        if len(crops) != len(set(crops)):
            raise ValueError("Provide only one budget override per crop")
        return self


class RotationBudgetSeason(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int = Field(ge=1, le=5)
    season: Literal["main", "cover"]
    crop: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")


class RotationBudgetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: list[RotationBudgetSeason] = Field(min_length=1, max_length=30)
    horizon_years: int | None = Field(default=None, ge=1, le=5)
    state: str = Field(pattern=r"^[A-Z]{2}$")
    area_ha: float | None = Field(default=None, gt=0, le=1000000, allow_inf_nan=False)
    previous_crop: str | None = Field(default=None, max_length=100)
    options: RotationBudgetOptions = Field(default_factory=RotationBudgetOptions)

    @field_validator("sequence")
    @classmethod
    def _valid_sequence(cls, value: list[RotationBudgetSeason]) -> list[RotationBudgetSeason]:
        keys = [(s.year, s.season, s.crop) for s in value]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate year, season and crop in sequence")
        if [s.year for s in value] != sorted(s.year for s in value):
            raise ValueError("Sequence must be ordered by year")
        if any(sum(s.year == year and s.season == "main" for s in value) > 2 for year in range(1, 6)):
            raise ValueError("At most two main crops per year are supported")
        return value

    @model_validator(mode="after")
    def _covers_sequence(self) -> "RotationBudgetRequest":
        if self.horizon_years is not None and max(s.year for s in self.sequence) > self.horizon_years:
            raise ValueError("horizon_years cannot precede a sequence year")
        return self


class AnalysisOptions(BaseModel):
    priorities: list[Priority] = Field(default_factory=list, max_length=6)
    crop_history: list[CropYear] | None = Field(default=None, max_length=10)
    horizon_years: int = Field(default=3, ge=1, le=5)
    budget: RotationBudgetOptions = Field(default_factory=RotationBudgetOptions)


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


class BudgetAmounts(BaseModel):
    low: float
    base: float
    high: float


class BudgetScenario(BaseModel):
    revenue_per_acre: float
    cost_per_acre: float
    profit_per_acre: float
    field_profit: float | None
    return_before_land_per_acre: float | None = None
    field_revenue: float | None = None
    field_cost: float | None = None


class BudgetScenarios(BaseModel):
    low: BudgetScenario
    base: BudgetScenario
    high: BudgetScenario


class BudgetYear(BaseModel):
    year: int
    main_crops: list[str]
    cover_crops: list[str]
    production_cost_per_acre: float | None
    land_rent_per_acre: float | None
    cover_cost_per_acre: float | None
    nitrogen_credit_per_acre: float
    yield_per_acre: float | None
    yield_unit: str | None
    scenarios: BudgetScenarios | None
    cost_profile: str | None = None
    break_even_price_per_unit: float | None = None
    yield_source: Literal["budget_reference", "baseline_default", "farmer", "unavailable"] = "unavailable"
    sources: list[DatasetRef] = Field(default_factory=list)


class RotationBudget(BaseModel):
    status: Literal["estimated", "partial", "unavailable"]
    currency: Literal["USD"] = "USD"
    horizon_years: int
    area_acres: float | None
    years: list[BudgetYear]
    annual_average: BudgetScenarios | None
    horizon_total: BudgetScenarios | None
    delta_vs_current_per_acre: BudgetAmounts | None = None
    is_illustrative: Literal[True] = True
    uses_placeholders: bool
    baseline_version: str
    assumptions: list[str]
    missing_inputs: list[str]
    sources: list[DatasetRef]


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
    budget: RotationBudget | None = Field(default=None, exclude_if=lambda v: v is None)


class AnalysisResult(BaseModel):
    selection: FieldSelection
    generated_at: datetime
    model_version: str
    current_conditions: list[Metric]
    time_series: list[TimeSeries] = Field(default_factory=list)
    strategies: list[Strategy] = Field(min_length=1)
    datasets_used: list[DatasetRef]
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str
    ml_analysis: dict[str, Any] | None = Field(default=None, exclude_if=lambda v: v is None)


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
    land_rent_per_acre: float | None = Field(default=None, ge=0, le=5000, allow_inf_nan=False)
    total_cost_per_acre: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    seed: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    fertilizer: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    chemicals: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    other_operating: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)

    @model_validator(mode="after")
    def _unambiguous_costs(self) -> "CostOverrides":
        if self.total_cost_per_acre is not None and any(
            getattr(self, key) is not None for key in ("seed", "fertilizer", "chemicals", "other_operating")
        ):
            raise ValueError("Itemized costs cannot accompany total_cost_per_acre")
        return self


class ProfitPriceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    low: float = Field(ge=0, le=1000, allow_inf_nan=False)
    base: float = Field(ge=0, le=1000, allow_inf_nan=False)
    high: float = Field(ge=0, le=1000, allow_inf_nan=False)

    @model_validator(mode="after")
    def _ordered(self) -> "ProfitPriceInput":
        if not self.low <= self.base <= self.high:
            raise ValueError("Prices must satisfy low <= base <= high")
        return self


class ProfitEstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    crop: ProfitCrop
    state: ProfitState
    predicted_yield: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    yield_per_acre: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    price_overrides: ProfitPriceInput | None = None
    area_ha: float | None = Field(default=None, gt=0, le=1000000, allow_inf_nan=False)
    previous_crop: str | None = Field(default=None, max_length=100)
    cost_overrides: CostOverrides = Field(default_factory=CostOverrides)

    @model_validator(mode="after")
    def _one_yield(self) -> "ProfitEstimateRequest":
        if self.predicted_yield is not None and self.yield_per_acre is not None:
            raise ValueError("Supply either predicted_yield or yield_per_acre, not both")
        return self


class ProfitScenario(BaseModel):
    price: float
    revenue_per_acre: float
    cost_per_acre: float
    profit_per_acre: float
    return_before_land_per_acre: float | None = None
    break_even_yield_per_acre: float | None = None
    field_revenue: float | None = None
    field_cost: float | None = None
    field_profit: float | None = None


class ProfitCostItem(BaseModel):
    key: Literal["seed", "fertilizer", "chemicals", "other_operating", "land_rent", "total"]
    label: str
    amount_per_acre: float
    source: Literal["baseline", "farmer", "baseline_with_nitrogen_credit", "baseline_rotation"]


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
    yield_per_acre: float | None
    yield_unit: str
    yield_source: Literal["model", "baseline_default", "budget_reference", "farmer", "unavailable"]
    costs: list[ProfitCostItem]
    scenarios: ProfitScenarios | None
    assumptions: list[str]
    baseline: ProfitBaselineInfo
    cost_profile: str | None = None
    status: Literal["estimated", "unavailable"]
    currency: Literal["USD"] = "USD"
    is_illustrative: Literal[True] = True
    price_source: Literal["baseline", "farmer", "unavailable"]
    area_acres: float | None = None
    break_even_price_per_unit: float | None = None
    missing_inputs: list[str]
    sources: list[DatasetRef]


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


# --- Comparisons ------------------------------------------------------------------------------------


class CropHistorySummary(BaseModel):
    """What a renter reads from past crops. Counts use the years on record, newest first."""

    source: Literal["farmer", "usda_csb", "none"]
    years_recorded: int
    first_year: int | None
    latest_year: int | None
    latest_crop: str | None
    corn_years: int
    soybean_years: int
    other_years: int
    distinct_crops: int
    # Consecutive corn years ending at the latest year (0 when the latest crop is not corn).
    corn_in_a_row: int
    pattern: Literal["corn_soybean", "continuous_corn", "continuous_soybean", "mixed", "unknown"]


class ComparisonPlanCrop(StrEnum):
    corn = "corn"
    soybean = "soybean"
    winter_wheat = "winter_wheat"


class ComparisonPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rotation: list[ComparisonPlanCrop] = Field(
        default_factory=lambda: [ComparisonPlanCrop.corn, ComparisonPlanCrop.soybean],
        min_length=1, max_length=3,
    )
    horizon_years: int = Field(default=2, ge=1, le=5)


class SavedFieldComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    saved_field_ids: list[UUID] = Field(min_length=2, max_length=4)
    # Asking cash rent per saved field id, USD/acre/year. Fields left out use the state reference rent.
    rent_per_acre: dict[str, float] = Field(default_factory=dict)
    plan: ComparisonPlan = Field(default_factory=ComparisonPlan)
    crop_overrides: list[CropBudgetInput] = Field(default_factory=list, max_length=16)
    home: LatLon | None = None

    @model_validator(mode="after")
    def _check(self) -> "SavedFieldComparisonRequest":
        if len(set(self.saved_field_ids)) != len(self.saved_field_ids):
            raise ValueError("saved_field_ids must be unique")
        ids = {str(i) for i in self.saved_field_ids}
        rents: dict[str, float] = {}
        for key, value in self.rent_per_acre.items():
            try:
                norm = str(UUID(key))
            except ValueError:
                raise ValueError(f"rent_per_acre key {key!r} is not a saved field id") from None
            if norm not in ids:
                raise ValueError(f"rent_per_acre key {key!r} is not in saved_field_ids")
            if not (0 <= value <= 5000) or value != value:
                raise ValueError("rent_per_acre values must be between 0 and 5000")
            rents[norm] = value
        self.rent_per_acre = rents
        crops = [x.crop for x in self.crop_overrides]
        if len(crops) != len(set(crops)):
            raise ValueError("Provide only one budget override per crop")
        return self


class RentUsed(BaseModel):
    per_acre: float | None
    source: Literal["farmer", "state_baseline", "none"]
    is_placeholder: bool


class ComparedField(BaseModel):
    saved_field_id: UUID
    label: str
    name: str
    field_id: str | None
    state: str
    county: CountyRef | None
    anchor: LatLon
    boundary_type: BoundaryType
    area_ha: float | None
    rent: RentUsed
    budget: RotationBudget | None
    net_return_per_acre: BudgetAmounts | None
    net_return_field: BudgetAmounts | None
    break_even_rent_per_acre: BudgetAmounts | None
    history: CropHistorySummary
    strengths: list[str]
    cautions: list[str]
    data_as_of: datetime | None
    info_as_of: datetime | None


class ValueRange(BaseModel):
    min: float
    max: float


class ComparisonCell(BaseModel):
    saved_field_id: UUID
    value: float | str | None
    quality: Quality
    note: str | None = None


class ComparisonRow(BaseModel):
    key: str
    label: str
    group: Literal["money", "land", "soil", "history", "climate"]
    unit: str
    better: Literal["higher", "lower", "target", "none"]
    target: ValueRange | None = None
    cells: list[ComparisonCell]
    best: list[UUID]
    same_for_all: bool
    note: str | None = None


class ComparisonBest(BaseModel):
    net_return: list[UUID]
    soil_productivity: list[UUID]
    rent_value: list[UUID]


class FieldComparison(BaseModel):
    generated_at: datetime
    plan: ComparisonPlan
    fields: list[ComparedField]
    rows: list[ComparisonRow]
    best: ComparisonBest
    warnings: list[str]
    disclaimer: str


class AreaCountyRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    county_fips: CountyFips


class AreaBBoxRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bbox: BBox


class AreaPolygonRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    polygon: GeoJSONPolygon


AreaRef = AreaCountyRef | AreaBBoxRef | AreaPolygonRef


class AreaFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_area_ha: float | None = Field(default=None, ge=0, le=100000)
    max_area_ha: float | None = Field(default=None, ge=0, le=100000)
    min_productivity: float | None = Field(default=None, ge=0, le=100)
    latest_crops: list[str] = Field(default_factory=list, max_length=10)
    exclude_continuous_corn: bool = False


class AreaSort(StrEnum):
    productivity = "productivity"
    area = "area"
    distance = "distance"


class AreaRankingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: AreaRef
    filters: AreaFilters = Field(default_factory=AreaFilters)
    sort: AreaSort = AreaSort.productivity
    near: LatLon | None = None
    pinned_field_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=4,
    )
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=50000)

    @model_validator(mode="after")
    def _check(self) -> "AreaRankingRequest":
        if self.sort == AreaSort.distance and self.near is None:
            raise ValueError("sort=distance needs `near`")
        f = self.filters
        if f.min_area_ha is not None and f.max_area_ha is not None and f.min_area_ha > f.max_area_ha:
            raise ValueError("min_area_ha must not exceed max_area_ha")
        return self


class Quartiles(BaseModel):
    p25: float
    median: float
    p75: float


class RankedField(BaseModel):
    field_id: str
    rank: int | None
    matches_filters: bool
    anchor: LatLon
    bbox: list[float]
    county_fips: str
    area_ha: float
    history: CropHistorySummary
    productivity: float | None
    soil_name: str | None
    drainage: str | None
    distance_km: float | None
    area_percentile: int | None
    productivity_percentile: int | None


class AreaSoilStatus(BaseModel):
    status: Literal["complete", "partial", "filling", "unavailable"]
    fields_rated: int
    fields_total: int
    method: str


class AreaInfo(BaseModel):
    kind: Literal["county", "bbox", "polygon"]
    county: CountyRef | None
    bbox: list[float]


class AreaStats(BaseModel):
    area_ha: Quartiles | None
    productivity: Quartiles | None


class AreaRanking(BaseModel):
    area: AreaInfo
    total: int
    sort: AreaSort
    offset: int
    limit: int
    next_offset: int | None
    soil: AreaSoilStatus
    stats: AreaStats
    items: list[RankedField]
    pinned: list[RankedField]
    notes: list[str]
