"""Process-wide services, loaded once at startup and stored on `app.state.services`."""

import json
import logging
from pathlib import Path
from typing import Any

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
            self._boundaries = Boundaries.load(d, settings.pilot_counties)
        except DataMissing as e:
            log.warning("boundaries unavailable: %s", e)

        self.fields_meta: dict[str, Any] = {}
        meta = d / "fields_meta.json"
        if meta.exists():
            self.fields_meta = json.loads(meta.read_text())

        # Imported here to keep geopandas-heavy modules out of import cycles.
        from app.geo.fields_index import FieldIndex

        self._fields: FieldIndex | None = None
        if (d / "fields.parquet").exists():
            self._fields = FieldIndex.load(d / "fields.parquet")
        else:
            log.warning("fields.parquet missing: point resolution falls back to buffered points")

        self.field_tiles = self._tiles(d / "fields.pmtiles")
        self.boundary_tiles = self._tiles(d / "boundaries.pmtiles")

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
    def fields(self):
        """FieldIndex, or None when no field data was prepared (everything is a buffered point)."""
        return self._fields

    def close(self) -> None:
        self.cache.close()
        for t in (self.field_tiles, self.boundary_tiles):
            if t:
                t.close()


def get_services(request: Request) -> Services:
    return request.app.state.services
