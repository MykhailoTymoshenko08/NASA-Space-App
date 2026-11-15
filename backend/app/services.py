"""Process-wide services, loaded once at startup and stored on `app.state.services`."""

import logging
import secrets
from pathlib import Path
from typing import Any

import httpx
from fastapi import Request

from app.core.cache import TwoLevelCache
from app.core.config import Settings
from app.core.errors import ApiException, ErrorCode
from app.geo.boundaries import Boundaries, DataMissing
from app.geo.tiles import TileSource

log = logging.getLogger(__name__)


def _missing(what: str) -> ApiException:
    return ApiException(
        ErrorCode.INTERNAL_ERROR,
        f"Server data not prepared ({what}). Run `make data` in backend/.",
    )


class Services:
    def __init__(self, settings: Settings):
        self.settings = settings
        d: Path = settings.data_dir
        self.cache = TwoLevelCache(settings.cache_dir)

        self._boundaries: Boundaries | None = None
        try:
            self._boundaries = Boundaries.load(d)
        except DataMissing as e:
            log.warning("boundaries unavailable: %s", e)

        from app.geo.field_store import FieldStore

        self._fields: FieldStore | None = (
            FieldStore.connect(settings.database_url) if settings.database_url else None
        )
        if self._fields is None:
            log.warning("no field polygons: point resolution falls back to buffered points")
        self.field_meta: dict[str, Any] = self._fields.meta() if self._fields else {}

        from app.geo.links import make_link_client, system_resolver

        self.link_client = make_link_client()
        self.dns_resolver = system_resolver

        from app.snapshots.service import SnapshotService

        self.data_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            headers={"User-Agent": "FieldShift/0.1 (NASA Space Apps demo)"},
            follow_redirects=True,
        )
        self.snapshots = SnapshotService(
            self.cache, self.data_client,
            source_timeout_s=settings.source_timeout_s, ttl_s=settings.snapshot_cache_ttl_s,
        )

        from app.field_info.service import FieldInfoService

        self.field_info = FieldInfoService(self.data_client, timeout_s=settings.source_timeout_s)

        from app.analyses.ml import MLAnalysisEngine
        from app.analyses.service import AnalysisService
        from app.analyses.store import InMemoryJobStore
        from app.analyses.stub import StubAnalysisEngine

        self.ml_client = httpx.AsyncClient(
            base_url=str(settings.ml_base_url).rstrip("/") + "/",
            timeout=httpx.Timeout(settings.ml_timeout_s, connect=min(5.0, settings.ml_timeout_s)),
            headers=({"X-ML-Token": settings.ml_api_token.get_secret_value()}
                     if settings.ml_api_token.get_secret_value() else None),
        )

        self.analyses = AnalysisService(
            InMemoryJobStore(),
            (StubAnalysisEngine(duration_s=settings.stub_duration_s)
             if settings.analysis_engine == "stub" else MLAnalysisEngine(self.ml_client)),
            self.snapshots,
            dedupe_ttl_s=settings.analysis_dedupe_ttl_s,
            fail_rate=settings.stub_fail_rate if settings.analysis_engine == "stub" else 0.0,
        )

        from app.comparisons.area import AreaRankingService, AreaStore, SoilFiller

        self.area_rankings: AreaRankingService | None = None
        area_store = AreaStore.connect(settings.database_url) if self._fields is not None else None
        if area_store is not None:
            filler = SoilFiller(area_store, self.data_client) if settings.area_soil_fill else None
            self.area_rankings = AreaRankingService(area_store, filler, settings.area_max_fields)

        self.boundary_tiles = self._tiles(d / "boundaries.pmtiles")
        self.plss_tiles = self._tiles(d / "plss.pmtiles")

        from app.auth.store import UserStore

        self.users: UserStore | None = (
            UserStore.connect(settings.database_url) if settings.database_url else None
        )
        from app.saved_fields.store import SavedFieldStore

        self.saved_fields: SavedFieldStore | None = None
        if self.users is not None:
            try:
                self.saved_fields = SavedFieldStore.attach(self.users.pool)
            except Exception as e:  # noqa: BLE001 - any DB failure means "saved fields unavailable"
                log.error("saved_fields table unavailable (%s): saved-field endpoints return 500", e)
        self.jwt_secret = settings.jwt_secret.get_secret_value()
        if not self.jwt_secret:
            log.warning("JWT_SECRET not set: using a random per-process secret (tokens die on restart)")
            self.jwt_secret = secrets.token_urlsafe(48)

        from app.auth.mail import PasswordResetMailer

        self.password_reset_mailer = PasswordResetMailer(settings)

    @staticmethod
    def _tiles(path: Path) -> TileSource | None:
        if not path.exists():
            log.warning("%s missing: tile endpoint returns 204", path.name)
            return None
        return TileSource(path)

    @property
    def boundaries(self) -> Boundaries:
        if self._boundaries is None:
            raise _missing("boundaries")
        return self._boundaries

    @property
    def boundaries_or_none(self) -> Boundaries | None:
        return self._boundaries

    @property
    def fields(self):
        """FieldStore over CSB polygons in PostGIS, or None when unavailable (all buffered points)."""
        return self._fields

    async def aclose(self) -> None:
        await self.analyses.aclose()
        if self.area_rankings is not None:
            await self.area_rankings.aclose()
        await self.ml_client.aclose()
        await self.link_client.aclose()
        await self.field_info.aclose()
        await self.snapshots.aclose()
        await self.data_client.aclose()
        self.cache.close()
        if self.boundary_tiles:
            self.boundary_tiles.close()
        if self.plss_tiles:
            self.plss_tiles.close()
        if self._fields:
            self._fields.close()
        if self.users:
            self.users.close()


def get_services(request: Request) -> Services:
    return request.app.state.services
