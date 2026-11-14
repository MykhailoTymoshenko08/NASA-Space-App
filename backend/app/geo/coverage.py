"""Build the `Coverage` response from the PLSS data actually prepared."""

from app.geo.crs import CONUS_BBOX
from app.models import Coverage, FieldBoundarySource, FieldTilesInfo
from app.services import Services

FIELD_TILE_URL = "/v1/tiles/fields/{z}/{x}/{y}.mvt"
PLSS_NAME = "BLM National PLSS (CadNSDI)"
PLSS_ATTRIBUTION = "Bureau of Land Management"


def unit_regions(svc: Services) -> list[dict]:
    """Areas with PLSS sections (one bbox per prepared state). Empty when no sections are loaded."""
    if svc.fields is None:
        return []
    return [{"name": r["name"], "bbox": r["bbox"]} for r in svc.plss_meta.get("regions", [])]


def build_coverage(svc: Services) -> Coverage:
    s = svc.settings
    meta = svc.plss_meta
    tiles = svc.field_tiles
    return Coverage(
        bounds=list(CONUS_BBOX),
        supported_states=sorted({st.postal for st in svc.boundaries.states}),
        field_data_version=meta.get("field_data_version", "unprepared"),
        field_boundary_source=FieldBoundarySource(
            name=PLSS_NAME,
            edition=meta.get("edition", "unprepared"),
            boundary_type="plss_section",
            attribution=PLSS_ATTRIBUTION,
        ),
        field_tiles=FieldTilesInfo(
            unit="plss_section",
            min_zoom=tiles.min_zoom if tiles else s.field_tiles_min_zoom,
            max_zoom=tiles.max_zoom if tiles else s.field_tiles_max_zoom,
            url_template=FIELD_TILE_URL,
            regions=unit_regions(svc),
        ),
    )
