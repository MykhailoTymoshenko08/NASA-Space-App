"""Point -> FieldSelection resolution (backend spec 5.4) and SelectionRef handling."""

import shapely

from app.core.errors import ApiException, ErrorCode, not_found
from app.geo.crs import in_conus_bbox, lonlat_to_5070, to_4326, xy_to_lonlat
from app.geo.fields_index import FieldRecord
from app.models import (
    BoundaryType,
    CountyRef,
    FieldIdRef,
    FieldSelection,
    GeoJSONPolygon,
    LatLon,
    PlssRef,
    PointRef,
    ResolvedBy,
    SelectionRef,
    SelectionSource,
)
from app.services import Services

BUFFER_SEGMENTS = 16  # quad_segs: 64 vertices around the circle


def outside_coverage(lat: float, lon: float) -> ApiException:
    return ApiException(
        ErrorCode.OUTSIDE_COVERAGE,
        "This point is outside the contiguous United States, which is all this tool covers for now.",
        {"point": {"lat": lat, "lon": lon}},
    )


def _polygon_json(poly: shapely.Polygon) -> GeoJSONPolygon:
    # shapely coordinates are (x=lon, y=lat): GeoJSON order, as required.
    rings = [poly.exterior, *poly.interiors]
    return GeoJSONPolygon(
        coordinates=[[[round(x, 7), round(y, 7)] for x, y in r.coords] for r in rings]
    )


def _bbox(poly: shapely.Polygon) -> list[float]:
    w, s, e, n = poly.bounds
    return [round(w, 7), round(s, 7), round(e, 7), round(n, 7)]


def _anchor(rec: FieldRecord) -> LatLon:
    # Representative point is guaranteed inside the polygon (a centroid is not, for L shapes).
    p = rec.geometry_5070.centroid
    if not rec.geometry_5070.contains(p):
        p = rec.geometry_5070.point_on_surface()
    lon, lat = xy_to_lonlat(p.x, p.y)
    return LatLon(lat=round(lat, 6), lon=round(lon, 6))


def _county_ref(svc: Services, x: float, y: float, fips_hint: str = "") -> CountyRef:
    b = svc.boundaries
    c = b.county(fips_hint) if fips_hint else None
    c = c or b.county_at(x, y)
    if c is None:
        raise ApiException(ErrorCode.OUTSIDE_COVERAGE, "No US county found for this point.")
    return b.ref(c)


def selection_from_field(
    svc: Services, rec: FieldRecord, resolved_by: ResolvedBy, source: SelectionSource,
    snap_distance_m: float = 0.0, anchor: LatLon | None = None,
) -> FieldSelection:
    """`anchor`: the clicked point when it lies inside the section; otherwise the section centroid."""
    anchor = anchor or _anchor(rec)
    x, y = lonlat_to_5070(anchor.lon, anchor.lat)
    return FieldSelection(
        field_id=rec.field_id,
        anchor=anchor,
        geometry=_polygon_json(rec.geometry),
        bbox=_bbox(rec.geometry),
        resolved_by=resolved_by,
        boundary_type=BoundaryType.plss_section,
        plss=PlssRef(
            township_id=rec.township_id,
            section_id=rec.section_id,
            section_number=rec.section_number,
            division_type=rec.division_type,
        ),
        label=rec.label,
        snap_distance_m=round(snap_distance_m, 1),
        buffer_m=None,
        area_ha=round(rec.area_ha, 2),
        crop_class=None,  # PLSS has no crop data
        county=_county_ref(svc, x, y, rec.county_fips),
        source=source,
        crop_history=[],
    )


def resolve_point(
    svc: Services,
    point: LatLon,
    snap_radius_m: float = 300.0,
    source: SelectionSource = SelectionSource.map_click,
) -> FieldSelection:
    lat, lon = point.lat, point.lon
    if not in_conus_bbox(lat, lon):
        raise outside_coverage(lat, lon)
    x, y = lonlat_to_5070(lon, lat)
    if not svc.boundaries.in_us(x, y):
        raise outside_coverage(lat, lon)

    idx = svc.fields
    if idx is not None:
        rec = idx.containing(x, y)
        if rec is not None:
            # Point lookups sample data at the clicked point, which lies inside the section.
            return selection_from_field(svc, rec, ResolvedBy.field_polygon, source, 0.0, anchor=point)
        hit = idx.nearest(x, y, snap_radius_m)
        if hit is not None:
            rec, dist = hit
            # The clicked point is outside the section, so sample at the section centroid instead.
            return selection_from_field(svc, rec, ResolvedBy.snapped_point, source, dist)

    # Fallback: a circle of buffer_m around the point, built in metres (EPSG:5070).
    r = svc.settings.buffer_radius_m
    circle_5070 = shapely.Point(x, y).buffer(r, quad_segs=BUFFER_SEGMENTS)
    circle = to_4326([circle_5070])[0]
    return FieldSelection(
        field_id=None,
        anchor=LatLon(lat=lat, lon=lon),
        geometry=_polygon_json(circle),
        bbox=_bbox(circle),
        resolved_by=ResolvedBy.buffered_point,
        boundary_type=BoundaryType.buffered_point,
        plss=None,
        label=None,
        snap_distance_m=None,
        buffer_m=r,
        area_ha=round(circle_5070.area / 10_000, 2),
        crop_class=None,
        county=_county_ref(svc, x, y),
        source=source,
        crop_history=[],
    )


def get_field_selection(
    svc: Services, field_id: str, source: SelectionSource = SelectionSource.landing_map_click
) -> FieldSelection:
    rec = svc.fields.get(field_id) if svc.fields is not None else None
    if rec is None:
        raise not_found(f"Unknown field_id {field_id!r}", field_id=field_id)
    return selection_from_field(svc, rec, ResolvedBy.field_polygon, source, 0.0)


def resolve_ref(
    svc: Services, ref: SelectionRef, source: SelectionSource = SelectionSource.map_click
) -> FieldSelection:
    if isinstance(ref, FieldIdRef):
        return get_field_selection(svc, ref.field_id, source)
    assert isinstance(ref, PointRef)
    return resolve_point(svc, ref.point, source=source)
