"""Runtime configuration, read from environment variables (and an optional `.env`)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent

# Central Iowa pilot: Polk, Story, Dallas, Boone.
DEFAULT_PILOT_REGION = "19153,19169,19049,19015"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    frontend_origin: str = "http://localhost:5173"
    data_dir: Path = BACKEND_DIR / "data"
    cache_dir: Path = BACKEND_DIR / ".cache"
    # Comma-separated 5-digit county FIPS codes where field polygons are prepared.
    pilot_region: str = DEFAULT_PILOT_REGION
    log_level: str = "INFO"

    contract_path: Path = REPO_DIR / "contract" / "openapi.yaml"

    # Analysis stub knobs.
    stub_fail_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    stub_duration_s: float = Field(default=6.0, ge=0.0)

    # Upstream data sources.
    source_timeout_s: float = 4.0
    snapshot_cache_ttl_s: int = 24 * 3600
    analysis_dedupe_ttl_s: int = 600

    # Rate limiting (per client IP, sliding window).
    rate_limit_requests: int = 30
    rate_limit_window_s: int = 60

    # Field resolution.
    field_tiles_min_zoom: int = 11
    field_tiles_max_zoom: int = 16
    buffer_radius_m: float = 500.0

    @field_validator("pilot_region")
    @classmethod
    def _check_region(cls, v: str) -> str:
        codes = [c.strip() for c in v.split(",") if c.strip()]
        for c in codes:
            if len(c) != 5 or not c.isdigit():
                raise ValueError(f"PILOT_REGION must be 5-digit county FIPS codes, got {c!r}")
        return ",".join(codes)

    @property
    def pilot_counties(self) -> list[str]:
        return [c for c in self.pilot_region.split(",") if c]


@lru_cache
def get_settings() -> Settings:
    return Settings()
