"""Runtime configuration, read from environment variables (and an optional `.env`)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent

# States with CSB field polygons (state FIPS -> postal). Fixed for the MVP: scripts/prepare_csb.py
# imports exactly these, and the geo endpoints list only these.
FIELD_STATES: dict[str, str] = {"17": "IL", "19": "IA", "31": "NE"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    frontend_origin: str = "http://localhost:5173"
    data_dir: Path = BACKEND_DIR / "data"
    cache_dir: Path = BACKEND_DIR / ".cache"
    # PostGIS with the CSB field polygons (scripts/prepare_csb.py). Empty: every point resolves to a
    # buffered point.
    database_url: str = "postgresql://fieldshift:fieldshift@localhost:5433/fieldshift"
    # Field PMTiles file in DATA_DIR, served by the backend at /v1/tiles/fields.pmtiles (HTTP Range).
    fields_pmtiles_file: str = "csb_ia_il_ne.pmtiles"
    # Optional override: absolute URL of the same file on external static hosting (CDN/R2). Empty means
    # /meta/coverage advertises the backend's own /v1/tiles/fields.pmtiles.
    fields_pmtiles_url: str = ""
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
    buffer_radius_m: float = 500.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
