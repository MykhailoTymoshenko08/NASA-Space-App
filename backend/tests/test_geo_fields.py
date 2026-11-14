"""/geo/*, /meta/coverage, /fields/*, boundary tiles, point resolution (CSB polygons in PostGIS)."""

import pytest

from app.geo.crs import lonlat_to_5070, xy_to_lonlat
from tests.contract import assert_matches_contract
from tests.fixture_data import (
    F1_HISTORY,
    F1_ID,
    F1_POINT,
    F2_ID,
    TEXAS_POINT,
    tile_for,
)

pytestmark = pytest.mark.contract


# ---------- geo ----------
def test_states_lists_only_supported(client):
    r = client.get("/v1/geo/states")
    assert_matches_contract(r)
    # Texas is in the boundary data but has no field polygons: not listed.
    assert [s["postal"] for s in r.json()["items"]] == ["IA"]


def test_counties_of_state_sorted_all_covered(client):
    r = client.get("/v1/geo/states/19/counties")
    assert_matches_contract(r)
    items = r.json()["items"]
    assert [c["name"] for c in items] == ["Polk", "Story"]
    assert all(c["has_field_coverage"] for c in items)


def test_unsupported_state_counties_not_found(client):
    r = client.get("/v1/geo/states/48/counties")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert_matches_contract(r)


def test_unsupported_county_has_no_coverage(client):
    r = client.get("/v1/geo/counties/48453")
    assert_matches_contract(r)
    assert r.json()["has_field_coverage"] is False


def test_county(client):
    r = client.get("/v1/geo/counties/19153")
    assert_matches_contract(r)
    c = r.json()
    w, s, e, n = c["bbox"]
    assert w < e and s < n and w < -90  # [west, south, east, north], lon first
    assert s <= c["centroid"]["lat"] <= n and w <= c["centroid"]["lon"] <= e


@pytest.mark.parametrize(
    "url", ["/v1/geo/counties/99999", "/v1/geo/states/02/counties", "/v1/fields/csb2025_unknown"]
)
def test_not_found(client, url):
    r = client.get(url)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert_matches_contract(r)


@pytest.mark.parametrize("url", [
    "/v1/geo/states/abc/counties", "/v1/geo/counties/abc",
    "/v1/tiles/boundaries/23/0/0.mvt", "/v1/tiles/boundaries/-1/0/0.mvt",
    "/v1/tiles/boundaries/7/-1/0.mvt", "/v1/tiles/boundaries/7/0/nope.mvt",
])
def test_invalid_path_is_contract_validation_error(client, url):
    r = client.get(url)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert_matches_contract(r)


# ---------- coverage ----------
def test_coverage(client):
    r = client.get("/v1/meta/coverage")
    assert_matches_contract(r)
    c = r.json()
    # Bounds = the supported states present in the boundary data (only Iowa in the fixture).
    assert c["bounds"] == [-93.8, 41.5, -93.4, 42.2]
    assert c["supported_states"] == ["IA", "IL", "NE"]
    ft = c["field_tiles"]
    assert ft["format"] == "pmtiles"
    assert ft["unit"] == "estimated_csb"
    # Served by this backend; absolute so a frontend on another origin can use it.
    assert ft["url_template"] == "http://localhost:8000/v1/tiles/fields.pmtiles"
    assert ft["min_zoom"] == 12 and ft["max_zoom"] == 14
    assert ft["regions"] == [{"name": "Iowa", "bbox": [-93.8, 41.5, -93.4, 42.2]}]
    assert c["field_data_version"] == "test-1"
    src = c["field_boundary_source"]
    assert src["name"] == "USDA Crop Sequence Boundaries"
    assert src["boundary_type"] == "estimated_csb"
    assert src["edition"] == "2018-2025"
    assert "Crop Sequence Boundaries" in src["attribution"]


def test_coverage_external_pmtiles_override(make_client, data_dir):
    c = make_client(data_dir, fields_pmtiles_url="https://tiles.example.org/csb_ia_il_ne.pmtiles")
    r = c.get("/v1/meta/coverage")
    assert_matches_contract(r)
    assert r.json()["field_tiles"]["url_template"] == "https://tiles.example.org/csb_ia_il_ne.pmtiles"


def test_coverage_without_field_db(make_client, data_dir):
    c = make_client(data_dir, database_url="")
    r = c.get("/v1/meta/coverage")
    assert_matches_contract(r)
    j = r.json()
    assert j["field_data_version"] == "unprepared"
    assert j["field_tiles"]["min_zoom"] == 12


# ---------- point resolution ----------
def _resolve(client, lat, lon, **kw):
    r = client.post("/v1/fields/resolve", json={"point": {"lat": lat, "lon": lon}, **kw})
    assert_matches_contract(r)
    return r


def test_point_inside_field(client):
    s = _resolve(client, *F1_POINT).json()
    assert s["field_id"] == F1_ID
    assert s["resolved_by"] == "field_polygon"
    assert s["boundary_type"] == "estimated_csb"
    assert "plss" not in s and "label" not in s
    assert s["snap_distance_m"] == 0
    assert s["source"] == "map_click"
    assert s["county"] == {"fips": "19153", "name": "Polk", "state_postal": "IA"}
    assert s["crop_class"] == "Corn"
    # Newest first, straight from the CSB history table.
    assert s["crop_history"] == [{"year": y, "crop": c} for y, c in F1_HISTORY]
    assert 30 < s["area_ha"] < 42  # ~600 m x 600 m
    # Point lookups sample at the clicked point.
    assert s["anchor"] == {"lat": F1_POINT[0], "lon": F1_POINT[1]}


def test_point_lookup_anchor_is_clicked_point(client):
    s = _resolve(client, 41.6010, -93.6010).json()
    assert s["boundary_type"] == "estimated_csb"
    assert s["anchor"] == {"lat": 41.6010, "lon": -93.6010}


def test_geometry_is_lon_lat(client):
    s = _resolve(client, *F1_POINT).json()
    ring = s["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    for lon, lat in ring:
        assert -94 < lon < -93 and 41 < lat < 42
    w, s_, e, n = s["bbox"]
    assert -94 < w < e < -93 and 41 < s_ < n < 42
    assert abs(s["anchor"]["lat"] - 41.60) < 0.01 and abs(s["anchor"]["lon"] + 93.60) < 0.01


def test_snaps_to_nearest_within_radius(client):
    # ~100 m south of F1 (F1 south edge is 41.5973).
    s = _resolve(client, 41.5964, -93.60).json()
    assert s["resolved_by"] == "snapped_point"
    assert s["field_id"] == F1_ID
    assert 80 < s["snap_distance_m"] < 120


def test_snap_radius_zero_buffers(client):
    s = _resolve(client, 41.5964, -93.60, snap_radius_m=0).json()
    assert s["resolved_by"] == "buffered_point"


def test_far_point_buffers_500m_circle(client):
    s = _resolve(client, 41.70, -93.70, source="coordinates").json()
    assert s["resolved_by"] == "buffered_point"
    assert s["boundary_type"] == "buffered_point"
    assert s["field_id"] is None
    assert s["crop_class"] is None and s["crop_history"] == []
    assert s["buffer_m"] == 500
    assert s["source"] == "coordinates"
    # pi * 500^2 m2 = 78.5 ha; polygon approximation is slightly smaller.
    assert 77.5 < s["area_ha"] < 78.6
    assert s["anchor"] == {"lat": 41.70, "lon": -93.70}
    # Circle radius really is 500 m (measured in EPSG:5070, not degrees).
    cx, cy = lonlat_to_5070(-93.70, 41.70)
    for lon, lat in s["geometry"]["coordinates"][0]:
        x, y = lonlat_to_5070(lon, lat)
        assert abs(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 - 500) < 1


@pytest.mark.parametrize(
    "lat,lon",
    [(51.0, -93.6), (41.6, -60.0), (20.0, -93.6), (-41.6, 93.6), (43.9, -79.0)],
)
def test_outside_coverage(client, lat, lon):
    r = client.post("/v1/fields/resolve", json={"point": {"lat": lat, "lon": lon}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "OUTSIDE_COVERAGE"
    assert_matches_contract(r)


def test_swapped_lat_lon_is_rejected(client):
    # The classic bug: lat/lon swapped. lat=-93.6 is invalid -> validation error.
    r = client.post("/v1/fields/resolve", json={"point": {"lat": -93.6, "lon": 41.6}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert_matches_contract(r)


@pytest.mark.parametrize(
    "body",
    [{}, {"point": [41.6, -93.6]}, {"point": {"lat": 41.6}}, {"point": {"lat": 41.6, "lon": -93.6},
                                                             "snap_radius_m": 5000}],
)
def test_resolve_validation(client, body):
    r = client.post("/v1/fields/resolve", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert_matches_contract(r)


def test_texas_point_is_buffered(client):
    s = _resolve(client, *TEXAS_POINT).json()
    assert s["boundary_type"] == "buffered_point"
    assert s["field_id"] is None
    assert s["county"] == {"fips": "48453", "name": "Travis", "state_postal": "TX"}


def test_get_field_by_id(client):
    r = client.get(f"/v1/fields/{F2_ID}")
    assert_matches_contract(r)
    s = r.json()
    assert s["source"] == "landing_map_click"
    assert s["resolved_by"] == "field_polygon"
    assert s["boundary_type"] == "estimated_csb"
    # F2 has no mapped crops: null / [], never guessed.
    assert s["crop_class"] is None and s["crop_history"] == []
    # Id lookups anchor at the polygon centroid (F2 is centred on -93.582, 41.60).
    assert abs(s["anchor"]["lon"] + 93.582) < 1e-3 and abs(s["anchor"]["lat"] - 41.60) < 1e-3


def test_no_field_data_falls_back_to_buffer(make_client, data_dir):
    c = make_client(data_dir, database_url="")
    r = c.post("/v1/fields/resolve", json={"point": {"lat": F1_POINT[0], "lon": F1_POINT[1]}})
    assert_matches_contract(r)
    assert r.json()["resolved_by"] == "buffered_point"


def test_crs_roundtrip():
    x, y = lonlat_to_5070(-93.6, 41.6)
    lon, lat = xy_to_lonlat(x, y)
    assert abs(lon + 93.6) < 1e-9 and abs(lat - 41.6) < 1e-9


# ---------- tiles ----------
def test_xyz_field_tile_endpoint_removed(client):
    # Field polygons are one PMTiles file (below); there is no XYZ field tile endpoint since v0.3.
    z, x, y = tile_for(*F1_POINT, 14)
    assert client.get(f"/v1/tiles/fields/{z}/{x}/{y}.mvt").status_code == 404


PMTILES = "/v1/tiles/fields.pmtiles"
ORIGIN = {"Origin": "http://localhost:5173"}


def test_fields_pmtiles_range_request(client, data_dir):
    size = (data_dir / "csb_ia_il_ne.pmtiles").stat().st_size
    r = client.get(PMTILES, headers={**ORIGIN, "Range": "bytes=0-126"})
    assert r.status_code == 206
    assert_matches_contract(r)
    assert r.headers["content-range"] == f"bytes 0-126/{size}"
    assert r.content[:7] == b"PMTiles" and len(r.content) == 127
    assert r.headers["etag"]
    assert r.headers["access-control-allow-origin"] == ORIGIN["Origin"]
    exposed = {h.strip().lower() for h in r.headers["access-control-expose-headers"].split(",")}
    assert {"etag", "content-range", "content-length"} <= exposed


def test_fields_pmtiles_full_and_head(client, data_dir):
    raw = (data_dir / "csb_ia_il_ne.pmtiles").read_bytes()
    r = client.get(PMTILES)
    assert r.status_code == 200 and r.content == raw
    assert r.headers["accept-ranges"] == "bytes"
    assert_matches_contract(r)
    h = client.head(PMTILES)
    assert h.status_code == 200 and int(h.headers["content-length"]) == len(raw)


def test_fields_pmtiles_preflight_allows_range(client):
    r = client.options(PMTILES, headers={
        **ORIGIN, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "range",
    })
    assert r.status_code == 200
    assert "range" in r.headers["access-control-allow-headers"].lower()


def test_fields_pmtiles_missing_is_404(make_client, data_dir):
    c = make_client(data_dir, fields_pmtiles_file="missing.pmtiles")
    r = c.get(PMTILES)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert_matches_contract(r)


def test_boundary_tile(client):
    z, x, y = tile_for(41.7, -93.6, 7)
    r = client.get(f"/v1/tiles/boundaries/{z}/{x}/{y}.mvt")
    assert r.status_code == 200
    assert_matches_contract(r)
    assert client.get("/v1/tiles/boundaries/7/0/0.mvt").status_code == 204
