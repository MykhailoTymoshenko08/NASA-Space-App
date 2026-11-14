"""Runtime configuration, read from environment variables (and an optional `.env`)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    frontend_origin: str = "http://localhost:5173"
    data_dir: Path = BACKEND_DIR / "data"
    cache_dir: Path = BACKEND_DIR / ".cache"
    # States whose BLM PLSS sections are prepared by scripts/prepare_plss.py.
    plss_states: str = "IA"
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
    field_tiles_max_zoom: int = 14
    buffer_radius_m: float = 500.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
