"""M1 + M2: /geo/*, /meta/coverage, /fields/*, tiles, point resolution."""

import pytest

from app.geo.crs import lonlat_to_5070, xy_to_lonlat
from tests.contract import assert_matches_contract
from tests.fixture_data import F1_POINT, FAKE_TILE, tile_for

pytestmark = pytest.mark.contract


# ---------- geo ----------
def test_states(client):
    r = client.get("/v1/geo/states")
    assert_matches_contract(r)
    assert r.json()["items"][0]["postal"] == "IA"


def test_counties_of_state_sorted_with_coverage(client):
    r = client.get("/v1/geo/states/19/counties")
    assert_matches_contract(r)
    items = r.json()["items"]
    assert [c["name"] for c in items] == ["Polk", "Story"]
    assert {c["fips"]: c["has_field_coverage"] for c in items} == {"19153": True, "19169": False}


def test_county(client):
    r = client.get("/v1/geo/counties/19153")
    assert_matches_contract(r)
    c = r.json()
    w, s, e, n = c["bbox"]
    assert w < e and s < n and w < -90  # [west, south, east, north], lon first
    assert s <= c["centroid"]["lat"] <= n and w <= c["centroid"]["lon"] <= e


@pytest.mark.parametrize(
    "url", ["/v1/geo/counties/99999", "/v1/geo/states/02/counties", "/v1/fields/fld_unknown00"]
)
def test_not_found(client, url):
    r = client.get(url)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert_matches_contract(r)


def test_bad_fips_is_validation_error(client):
    r = client.get("/v1/geo/counties/abc")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------- coverage ----------
def test_coverage(client):
    r = client.get("/v1/meta/coverage")
    assert_matches_contract(r)
    c = r.json()
    assert c["bounds"] == [-125.0, 24.4, -66.9, 49.6]
    ft = c["field_tiles"]
    assert ft["unit"] == "plss_section"
    assert ft["url_template"] == "/v1/tiles/fields/{z}/{x}/{y}.mvt"
    assert ft["min_zoom"] == 11 and ft["max_zoom"] == 14
    # Regions come from the PLSS data actually present, never "all of CONUS".
    assert [g["name"] for g in ft["regions"]] == ["IA (PLSS)"]
    assert c["field_data_version"] == "test-1"
    src = c["field_boundary_source"]
    assert src["name"] == "BLM National PLSS (CadNSDI)"
    assert src["boundary_type"] == "plss_section"
    assert src["edition"] == "2026-11-14"
    assert src["attribution"] == "Bureau of Land Management"


def test_counties_coverage_follows_sections(client):
    items = client.get("/v1/geo/states/19/counties").json()["items"]
    by = {c["fips"]: c["has_field_coverage"] for c in items}
    assert by == {"19153": True, "19169": False}


def test_coverage_without_fields_advertises_no_regions(make_client, empty_data_dir):
    c = make_client(empty_data_dir)
    r = c.get("/v1/meta/coverage")
    assert_matches_contract(r)
    assert r.json()["field_tiles"]["regions"] == []


# ---------- point resolution ----------
def _resolve(client, lat, lon, **kw):
    r = client.post("/v1/fields/resolve", json={"point": {"lat": lat, "lon": lon}, **kw})
    assert_matches_contract(r)
    return r


def test_point_inside_section(client):
    s = _resolve(client, *F1_POINT).json()
    assert s["field_id"] == "plss:IA050790N0240W0SN140"
    assert s["resolved_by"] == "field_polygon"
    assert s["boundary_type"] == "plss_section"
    assert s["plss"] == {
        "township_id": "IA050790N0240W0", "section_id": "IA050790N0240W0SN140",
        "section_number": "14", "division_type": "Section",
    }
    assert s["label"] == "Section 14, T79N R24W"
    assert s["snap_distance_m"] == 0
    assert s["source"] == "map_click"
    assert s["county"] == {"fips": "19153", "name": "Polk", "state_postal": "IA"}
    # PLSS has no crop data: never guessed.
    assert s["crop_class"] is None and s["crop_history"] == []
    # Point lookups sample at the clicked point.
    assert s["anchor"] == {"lat": F1_POINT[0], "lon": F1_POINT[1]}


def test_point_lookup_anchor_is_clicked_point(client):
    s = _resolve(client, 41.6010, -93.6010).json()
    assert s["boundary_type"] == "plss_section"
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
    assert s["field_id"] == "plss:IA050790N0240W0SN140"
    assert 80 < s["snap_distance_m"] < 120


def test_snap_radius_zero_buffers(client):
    s = _resolve(client, 41.5964, -93.60, snap_radius_m=0).json()
    assert s["resolved_by"] == "buffered_point"


def test_far_point_buffers_500m_circle(client):
    s = _resolve(client, 41.70, -93.70, source="coordinates").json()
    assert s["resolved_by"] == "buffered_point"
    assert s["boundary_type"] == "buffered_point"
    assert s["field_id"] is None and s["plss"] is None and s["label"] is None
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


def test_get_field_by_id(client):
    r = client.get("/v1/fields/plss:IA050790N0240W0SN130")
    assert_matches_contract(r)
    s = r.json()
    assert s["source"] == "landing_map_click"
    assert s["resolved_by"] == "field_polygon"
    assert s["boundary_type"] == "plss_section"
    assert s["label"] == "Section 13, T79N R24W"
    # Id lookups anchor at the section centroid (F2 is centred on -93.582, 41.60).
    assert abs(s["anchor"]["lon"] + 93.582) < 1e-3 and abs(s["anchor"]["lat"] - 41.60) < 1e-3


def test_no_field_data_falls_back_to_buffer(make_client, empty_data_dir):
    c = make_client(empty_data_dir)
    r = c.post("/v1/fields/resolve", json={"point": {"lat": F1_POINT[0], "lon": F1_POINT[1]}})
    assert_matches_contract(r)
    assert r.json()["resolved_by"] == "buffered_point"


def test_crs_roundtrip():
    x, y = lonlat_to_5070(-93.6, 41.6)
    lon, lat = xy_to_lonlat(x, y)
    assert abs(lon + 93.6) < 1e-9 and abs(lat - 41.6) < 1e-9


# ---------- tiles ----------
def test_field_tile_served_gzip(client):
    z, x, y = tile_for(*F1_POINT, 14)
    r = client.get(f"/v1/tiles/fields/{z}/{x}/{y}.mvt")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert r.headers["content-encoding"] == "gzip"
    # httpx transparently decodes gzip.
    import gzip

    assert r.content == gzip.decompress(FAKE_TILE)
    assert_matches_contract(r)


@pytest.mark.parametrize(
    "z,lat,lon",
    [(10, *F1_POINT), (14, 30.0, -100.0), (17, *F1_POINT)],
)
def test_field_tile_empty(client, z, lat, lon):
    z, x, y = tile_for(lat, lon, z)
    r = client.get(f"/v1/tiles/fields/{z}/{x}/{y}.mvt")
    assert r.status_code == 204
    assert r.content == b""
    assert_matches_contract(r)


def test_out_of_range_tile_coords(client):
    assert client.get("/v1/tiles/fields/12/99999/1.mvt").status_code == 204
    r = client.get("/v1/tiles/fields/23/1/1.mvt")
    assert r.status_code == 422


def test_boundary_tile(client):
    z, x, y = tile_for(41.7, -93.6, 7)
    r = client.get(f"/v1/tiles/boundaries/{z}/{x}/{y}.mvt")
    assert r.status_code == 200
    assert_matches_contract(r)
    assert client.get("/v1/tiles/boundaries/7/0/0.mvt").status_code == 204
