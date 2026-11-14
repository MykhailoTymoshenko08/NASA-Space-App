"""Pydantic models for docs/api_contract.md (v1). Request models forbid unknown keys on
purpose: contract drift between backend and ML should fail loudly during integration."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- request

class Geometry(_Strict):
    type: Literal["Polygon", "MultiPolygon"]
    coordinates: list[Any]

    @model_validator(mode="after")
    def _check_coordinates(self):
        polygons = [self.coordinates] if self.type == "Polygon" else self.coordinates
        try:
            if not polygons:
                raise ValueError("empty coordinates")
            for polygon in polygons:
                if not polygon:
                    raise ValueError("polygon has no rings")
                for ring in polygon:
                    _check_ring(ring)
        except (TypeError, IndexError) as exc:
            raise ValueError(f"malformed GeoJSON coordinates: {exc}") from exc
        return self


def _check_ring(ring: list) -> None:
    if len(ring) < 4:
        raise ValueError("a linear ring needs at least 4 positions")
    for pos in ring:
        lon, lat = float(pos[0]), float(pos[1])
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"position out of WGS84 range: [{lon}, {lat}] (GeoJSON order is [lon, lat])")
    if list(ring[0][:2]) != list(ring[-1][:2]):
        raise ValueError("linear ring is not closed (first and last position differ)")


class Centroid(_Strict):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Admin(_Strict):
    country: str = "US"
    state: str = Field(pattern=r"^[A-Za-z]{2}$", description="USPS code, e.g. IA")
    state_fips: str | None = None
    county_fips: str | None = None

    @field_validator("state")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class CropHistoryItem(_Strict):
    year: int = Field(ge=1990, le=2100)
    crop: str = Field(min_length=1)
    cdl_code: int | None = Field(default=None, ge=0, le=255)


class Soil(_Strict):
    texture: str | None = None
    organic_matter_pct: float | None = Field(default=None, ge=0, le=100)
    drainage_class: str | None = None
    hydrologic_group: str | None = None
    awc_cm_cm: float | None = Field(default=None, ge=0, le=1)
    slope_pct: float | None = Field(default=None, ge=0, le=100)


class FieldInput(_Strict):
    field_id: str = Field(min_length=1)
    geometry: Geometry | None = None
    centroid: Centroid | None = None
    area_ha: float | None = Field(default=None, gt=0)
    admin: Admin
    crop_history: list[CropHistoryItem] | None = None
    soil: Soil | None = None

    @model_validator(mode="after")
    def _geometry_or_centroid(self):
        if self.geometry is None and self.centroid is None:
            raise ValueError("field needs geometry or at least centroid")
        return self


class Priorities(_Strict):
    water: float = Field(default=0.5, ge=0, le=1)
    soil_health: float = Field(default=0.5, ge=0, le=1)
    nitrogen: float = Field(default=0.5, ge=0, le=1)
    erosion: float = Field(default=0.5, ge=0, le=1)
    income: float = Field(default=0.5, ge=0, le=1)


class Scenario(_Strict):
    temp_delta_c: float = Field(default=0.0, ge=-2, le=4)
    precip_change_pct: float = Field(default=0.0, ge=-40, le=20)


class FarmerInput(_Strict):
    irrigated: bool | None = None
    # list of crop slugs; shape is not fixed by the contract, a plain list is the simplest
    current_rotation: list[str] | None = None
    excluded_crops: list[str] = Field(default_factory=list)
    has_livestock: bool | None = None


class Options(_Strict):
    n_strategies: int = Field(default=3, ge=1, le=5)
    language: Literal["en", "uk"] = "en"
    include_monthly_series: bool = False


class AnalyzeRequest(_Strict):
    request_id: str | None = None
    field: FieldInput
    priorities: Priorities = Field(default_factory=Priorities)
    scenario: Scenario = Field(default_factory=Scenario)
    farmer_input: FarmerInput = Field(default_factory=FarmerInput)
    options: Options = Field(default_factory=Options)


# ---------------------------------------------------------------- response

class DetectedRotation(BaseModel):
    sequence: list[str]
    label: str
    confidence: float = Field(ge=0, le=1)
    years_used: list[int]
    source: Literal["csb", "farmer_input", "model_prior"]
    cycle_years: int | None = None                  # added in the real mode: length of one cycle


class KeyNumber(BaseModel):
    id: str
    label: str
    value: float
    unit: str
    source_ids: list[str]


class Summary(BaseModel):
    headline: str
    overall_risk: Literal["low", "medium", "high"]
    key_numbers: list[KeyNumber]


Flag = Literal["bare", "drought", "heat", "frost", "extreme_rain", "waterlogging"]


class TimelineMonth(BaseModel):
    month: int = Field(ge=1, le=12)
    bare_soil: float = Field(ge=0, le=1)
    moisture_deficit: float = Field(ge=0, le=1)
    heat_stress: float = Field(ge=0, le=1)
    frost_risk: float = Field(ge=0, le=1)
    extreme_precip: float = Field(ge=0, le=1)
    flags: list[Flag]
    bare_soil_source: Literal["crop_calendar", "landsat_ndvi"] | None = None     # added in the real mode


class SequenceItem(BaseModel):
    year: int = Field(ge=1)
    season: Literal["main", "cover"]
    crop: str


class Scores(BaseModel):
    water: int = Field(ge=0, le=100)
    soil_health: int = Field(ge=0, le=100)
    nitrogen: int = Field(ge=0, le=100)
    erosion: int = Field(ge=0, le=100)
    income: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class Deltas(BaseModel):
    water: int
    soil_health: int
    nitrogen: int
    erosion: int
    income: int
    overall: int


class Metrics(BaseModel):
    water_use_mm_yr: int
    n_fixed_kg_ha_yr: int
    bare_days_yr: int
    erosion_t_ha_yr: float


class Evidence(BaseModel):
    text: str
    source_ids: list[str]


class Strategy(BaseModel):
    id: str
    is_current: bool
    name: str
    sequence: list[SequenceItem]
    scores: Scores
    delta_vs_current: Deltas | None
    metrics: Metrics
    why: str
    evidence: list[Evidence]
    benefits: list[str]
    risks: list[str]
    data_gaps: list[str]
    check_with_agronomist: list[str]
    confidence: float = Field(ge=0, le=1)


class Source(BaseModel):
    id: str
    name: str
    variable: str
    resolution: str
    period: str


class CropSuitability(BaseModel):
    """one row of the crop ranking (added in the real mode)"""
    crop: str
    name: str
    group: Literal["cereal", "legume", "other"]
    fit_score: float = Field(ge=0, le=100)         # how well the FIELD suits the crop, without last year's crop (absolute)
    next_year_share: float = Field(ge=0, le=100)   # advice for next year with the real previous crop; adds up to 100 over not blocked
    rank: int = Field(ge=1)                        # by next_year_share
    blocked: bool
    block_reasons: list[str]
    explanation: str                               # in plain words, e.g. why a crop that suits the field is not on top
    top_factors: list[str]
    top3_role: str | None = None
    model_class: bool | None = None
    role: str | None = None                        # "cover" for a cover crop (never offered as a main crop)
    parts: dict[str, Any] | None = None


class AnalyzeResponse(BaseModel):
    request_id: str
    field_id: str
    model_version: str
    generated_at: str
    status: Literal["ok", "partial"]
    detected_rotation: DetectedRotation
    summary: Summary
    vulnerability_timeline: list[TimelineMonth] = Field(min_length=12, max_length=12)
    strategies: list[Strategy] = Field(min_length=1)
    sources: list[Source]
    warnings: list[str]
    disclaimer: str
    # added in the real mode, all optional so old clients keep working
    crop_suitability: list[CropSuitability] | None = None
    score_notes: dict[str, str] | None = None
    feature_source: Literal["precomputed", "tables", "on_the_fly"] | None = None


# ---------------------------------------------------------------- health / meta

class Coverage(BaseModel):
    states: list[str]
    years: list[int]


class HealthResponse(BaseModel):
    status: str
    model_version: str
    coverage: Coverage
    mode: str | None = None                         # "real" or "mock"


class CropMeta(BaseModel):
    crop: str
    cdl_code: int
    name_en: str
    name_uk: str
    type: Literal["cash", "legume", "cover", "perennial"]


class CropsResponse(BaseModel):
    crops: list[CropMeta]
