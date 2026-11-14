"""Build the `Coverage` response: the supported states, the field data in PostGIS and the PMTiles URL."""

from app.core.config import FIELD_STATES
from app.geo.crs import CONUS_BBOX
from app.models import Coverage, FieldBoundarySource, FieldTilesInfo
from app.services import Services

CSB_NAME = "USDA Crop Sequence Boundaries"
CSB_ATTRIBUTION = (
    "USDA NASS Crop Sequence Boundaries (algorithmic estimates of field areas, not surveyed or "
    "ownership boundaries)"
)
# Used only until the tile build has recorded the zooms it actually built (field_data_meta.tiles).
DEFAULT_MIN_ZOOM, DEFAULT_MAX_ZOOM = 12, 14


def _union(bboxes: list[list[float]]) -> list[float]:
    if not bboxes:
        return list(CONUS_BBOX)
    return [
        min(b[0] for b in bboxes), min(b[1] for b in bboxes),
        max(b[2] for b in bboxes), max(b[3] for b in bboxes),
    ]


def build_coverage(svc: Services, pmtiles_url: str) -> Coverage:
    meta = svc.field_meta
    tiles = meta.get("tiles", {})
    states = svc.boundaries.field_states
    return Coverage(
        bounds=_union([s.bbox for s in states]),
        supported_states=sorted(FIELD_STATES.values()),
        field_data_version=meta.get("field_data_version", "unprepared"),
        field_boundary_source=FieldBoundarySource(
            name=CSB_NAME,
            edition=meta.get("edition", "unprepared"),
            attribution=CSB_ATTRIBUTION,
        ),
        field_tiles=FieldTilesInfo(
            min_zoom=tiles.get("min_zoom", DEFAULT_MIN_ZOOM),
            max_zoom=tiles.get("max_zoom", DEFAULT_MAX_ZOOM),
            url_template=pmtiles_url,
            regions=[{"name": s.name, "bbox": s.bbox} for s in states],
        ),
    )
