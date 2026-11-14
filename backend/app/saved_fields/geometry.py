"""Validate a saved field's GeoJSON and derive its centroid, area and state.

Coverage uses the same rough state envelopes as `/fields/info` (no GIS data needed). Where two
envelopes overlap (the Missouri and Mississippi borders), the county boundaries break the tie when
they are loaded.
"""

import math
from dataclasses import dataclass

import shapely

from app.core.errors import ApiException, ErrorCode
from app.field_info.service import STATE_BOUNDS
from app.geo.boundaries import Boundaries
from app.geo.crs import lonlat_to_5070, to_5070
from app.geo.resolve import _anchor
from app.models import GeoJSONPoint, GeoJSONPolygon, LatLon

MAX_RINGS = 20
MAX_VERTICES = 2000
MAX_AREA_HA = 2000.0  # ~4,900 acres: larger than any real field, small enough to catch a bad drawing


@dataclass(frozen=True)
class Placement:
    geometry: dict
    centroid: LatLon
    area_ha: float | None
    state: str


def invalid(field: str, message: str) -> ApiException:
    """Same envelope as request validation errors (see core/errors.py)."""
    return ApiException(
        ErrorCode.VALIDATION_ERROR,
        f"Invalid request: {field}: {message}",
        {"field": field, "errors": [{"field": field, "message": message}]},
    )


def outside_coverage(lat: float, lon: float) -> ApiException:
    return ApiException(
        ErrorCode.OUTSIDE_COVERAGE,
        "Fields can be saved only in Iowa, Illinois and Nebraska.",
        {"supported_states": sorted(STATE_BOUNDS), "point": {"lat": lat, "lon": lon}},
    )


def _candidates(lat: float, lon: float) -> list[str]:
    return [s for s, (w, so, e, n) in STATE_BOUNDS.items() if w <= lon <= e and so <= lat <= n]


def _check_position(pos: list[float], field: str) -> tuple[float, float]:
    if len(pos) != 2:
        raise invalid(field, "Each position must be [lon, lat].")
    lon, lat = pos
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        raise invalid(field, "Coordinates must be finite WGS84 [lon, lat] values.")
    if not _candidates(lat, lon):
        raise outside_coverage(lat, lon)
    return lon, lat


def state_at(lat: float, lon: float, boundaries: Boundaries | None) -> str:
    cands = _candidates(lat, lon)
    if not cands:
        raise outside_coverage(lat, lon)
    if len(cands) > 1 and boundaries is not None:
        county = boundaries.county_at(*lonlat_to_5070(lon, lat))
        if county is not None and county.state_postal in cands:
            return county.state_postal
    return cands[0]


def place(geom: GeoJSONPoint | GeoJSONPolygon, boundaries: Boundaries | None) -> Placement:
    if isinstance(geom, GeoJSONPoint):
        lon, lat = _check_position(geom.coordinates, "geometry.coordinates")
        return Placement(
            geometry={"type": "Point", "coordinates": [lon, lat]},
            centroid=LatLon(lat=lat, lon=lon),
            area_ha=None,
            state=state_at(lat, lon, boundaries),
        )

    rings = geom.coordinates
    field = "geometry.coordinates"
    if not rings:
        raise invalid(field, "A polygon needs an exterior ring.")
    if len(rings) > MAX_RINGS:
        raise invalid(field, f"A polygon may have at most {MAX_RINGS} rings.")
    if sum(len(r) for r in rings) > MAX_VERTICES:
        raise invalid(field, f"A polygon may have at most {MAX_VERTICES} positions.")
    clean: list[list[tuple[float, float]]] = []
    for i, ring in enumerate(rings):
        if len(ring) < 4:
            raise invalid(f"{field}.{i}", "Each ring needs at least 4 positions (a closed triangle).")
        pts = [_check_position(p, f"{field}.{i}") for p in ring]
        if pts[0] != pts[-1]:
            raise invalid(f"{field}.{i}", "Each ring must be closed: the last position must equal the first.")
        clean.append(pts)

    poly = shapely.Polygon(clean[0], clean[1:])
    if not poly.is_valid:
        raise invalid(field, f"The polygon is not valid ({shapely.is_valid_reason(poly)}).")
    area_ha = to_5070([poly])[0].area / 10_000
    if area_ha <= 0:
        raise invalid(field, "The polygon has no area.")
    if area_ha > MAX_AREA_HA:
        raise invalid(field, f"The polygon is larger than {MAX_AREA_HA:.0f} ha.")
    centroid = _anchor(poly)
    return Placement(
        geometry={"type": "Polygon", "coordinates": [[list(p) for p in r] for r in clean]},
        centroid=centroid,
        area_ha=round(area_ha, 2),
        state=state_at(centroid.lat, centroid.lon, boundaries),
    )
