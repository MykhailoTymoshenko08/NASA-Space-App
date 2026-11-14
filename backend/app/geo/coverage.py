"""Build the `Coverage` response."""

from app.geo.crs import CONUS_BBOX
from app.models import Coverage, FieldBoundarySource, FieldTilesInfo
from app.services import Services

FIELD_TILE_URL = "/v1/tiles/fields/{z}/{x}/{y}.mvt"

CSB_DEFAULT_SOURCE = {
    "name": "USDA Crop Sequence Boundaries",
    "edition": "unknown",
    "estimated_csb": True,
    "attribution": "USDA NASS Crop Sequence Boundaries (algorithmic field polygons, not surveyed).",
    "url": "https://www.nass.usda.gov/Research_and_Science/Crop-Sequence-Boundaries/",
}


def pilot_regions(svc: Services) -> list[dict]:
    regions = []
    for fips in svc.settings.pilot_counties:
        c = svc.boundaries.county(fips)
        if c:
            regions.append({"name": f"{c.name} County, {c.state_postal}", "bbox": c.bbox})
    return regions


def build_coverage(svc: Services) -> Coverage:
    s = svc.settings
    meta = svc.fields_meta
    src = {**CSB_DEFAULT_SOURCE, **meta.get("field_boundary_source", {})}
    supported = sorted({st.postal for st in svc.boundaries.states})
    tiles = svc.field_tiles
    return Coverage(
        bounds=list(CONUS_BBOX),
        supported_states=supported,
        field_data_version=meta.get("field_data_version", "unprepared"),
        field_boundary_source=FieldBoundarySource(**src),
        field_tiles=FieldTilesInfo(
            min_zoom=tiles.min_zoom if tiles else s.field_tiles_min_zoom,
            max_zoom=tiles.max_zoom if tiles else s.field_tiles_max_zoom,
            url_template=FIELD_TILE_URL,
            # Only advertise regions we can actually serve.
            regions=pilot_regions(svc) if svc.fields else [],
        ),
    )
