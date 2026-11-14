"""Checks against the real prepared data (data/ from `make data`). Skipped when it is not built.

Points chosen from the actual data: Ames, Iowa lies inside the prepared PLSS sections; Austin, Texas
is outside the PLSS altogether (Texas was never surveyed under PLSS).
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app
from tests.contract import BASE_URL, assert_matches_contract

REAL = get_settings().data_dir
pytestmark = [
    pytest.mark.contract,
    pytest.mark.skipif(not (REAL / "sections.parquet").exists(), reason="run `make data` first"),
]

INSIDE = {"lat": 42.0308, "lon": -93.6319}  # Ames, IA
OUTSIDE = {"lat": 30.2672, "lon": -97.7431}  # Austin, TX


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    s = Settings(data_dir=REAL, cache_dir=tmp_path_factory.mktemp("cache"), log_level="WARNING")
    with TestClient(create_app(s), base_url=BASE_URL) as c:
        yield c


def test_point_inside_plss_is_section(real):
    r = real.post("/v1/fields/resolve", json={"point": INSIDE})
    assert_matches_contract(r)
    s = r.json()
    assert s["boundary_type"] == "plss_section"
    assert s["field_id"].startswith("plss:IA")
    assert s["plss"]["section_id"] in s["field_id"]
    assert s["label"].startswith("Section ")
    assert 100 < s["area_ha"] < 400  # about 259 ha (1 sq mile)
    assert s["county"]["name"] == "Story"
    by_id = real.get(f"/v1/fields/{s['field_id']}")
    assert_matches_contract(by_id)
    assert by_id.json()["field_id"] == s["field_id"]


def test_point_outside_plss_is_buffered(real):
    r = real.post("/v1/fields/resolve", json={"point": OUTSIDE})
    assert_matches_contract(r)
    s = r.json()
    assert s["boundary_type"] == "buffered_point"
    assert s["field_id"] is None
    assert s["county"]["state_postal"] == "TX"


def test_coverage_regions_are_real(real):
    c = real.get("/v1/meta/coverage").json()
    assert c["field_tiles"]["unit"] == "plss_section"
    assert c["field_tiles"]["regions"]
    assert c["field_tiles"]["regions"] != [{"name": "CONUS", "bbox": c["bounds"]}]
    story = real.get("/v1/geo/counties/19169").json()
    travis = real.get("/v1/geo/counties/48453").json()
    assert story["has_field_coverage"] is True and travis["has_field_coverage"] is False
