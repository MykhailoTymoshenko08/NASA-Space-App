"""Runtime configuration, read from environment variables (and an optional `.env`)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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

    # Auth. Users and refresh tokens live in the `database_url` database.
    # JWT_SECRET signs access tokens. Empty: a random per-process secret (dev only: tokens die on restart).
    jwt_secret: SecretStr = SecretStr("")
    access_token_ttl_min: int = Field(default=15, ge=1)
    refresh_token_ttl_days: int = Field(default=7, ge=1)
    # Refresh cookie. Frontend on another *site* (not just another port): SECURE=true, SAMESITE=none.
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # Saved fields (per user, in the `database_url` database).
    saved_fields_max_per_user: int = Field(default=50, ge=1)

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, v: SecretStr) -> SecretStr:
        if v.get_secret_value() and len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    @model_validator(mode="after")
    def _samesite_none_needs_secure(self) -> "Settings":
        if self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=true")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
