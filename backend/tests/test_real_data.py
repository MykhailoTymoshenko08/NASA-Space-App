"""Checks against the real prepared data (data/ from `make data`, CSB in the DATABASE_URL PostGIS).

Skipped when the real database has no imported fields. Points: Ames, Iowa is farmland covered by CSB;
Austin, Texas is outside the supported states (buffered point).
"""

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app
from tests.contract import BASE_URL, assert_matches_contract

REAL = get_settings()


def _has_fields() -> bool:
    try:
        with psycopg.connect(REAL.database_url, connect_timeout=3) as c:
            return c.execute("SELECT to_regclass('public.fields') IS NOT NULL").fetchone()[0]
    except Exception:  # noqa: BLE001
        return False


pytestmark = [
    pytest.mark.contract,
    pytest.mark.skipif(
        not ((REAL.data_dir / "states.json").exists() and _has_fields()),
        reason="run `make data` first",
    ),
]

# A soybean/corn field just south-west of Ames, IA (checked against the 2018-2025 CSB import).
INSIDE = {"lat": 41.9800, "lon": -93.7000}
OUTSIDE = {"lat": 30.2672, "lon": -97.7431}  # Austin, TX


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    s = Settings(cache_dir=tmp_path_factory.mktemp("cache"), log_level="WARNING")
    with TestClient(create_app(s), base_url=BASE_URL) as c:
        yield c


def test_point_in_iowa_is_csb_field(real):
    r = real.post("/v1/fields/resolve", json={"point": INSIDE, "snap_radius_m": 300})
    assert_matches_contract(r)
    s = r.json()
    assert s["boundary_type"] == "estimated_csb"
    assert s["field_id"].startswith("csb2025_19")
    assert s["county"]["state_postal"] == "IA"
    assert 0 < s["area_ha"] < 1000
    # 8-year CSB window: history is newest first and never longer than 8.
    years = [h["year"] for h in s["crop_history"]]
    assert years == sorted(years, reverse=True) and 0 < len(years) <= 8
    by_id = real.get(f"/v1/fields/{s['field_id']}")
    assert_matches_contract(by_id)
    assert by_id.json()["field_id"] == s["field_id"]
    assert by_id.json()["crop_history"] == s["crop_history"]


def test_point_in_texas_is_buffered(real):
    r = real.post("/v1/fields/resolve", json={"point": OUTSIDE})
    assert_matches_contract(r)
    s = r.json()
    assert s["boundary_type"] == "buffered_point"
    assert s["field_id"] is None
    assert s["county"]["state_postal"] == "TX"


def test_coverage_is_three_states(real):
    r = real.get("/v1/meta/coverage")
    assert_matches_contract(r)
    c = r.json()
    assert c["supported_states"] == ["IA", "IL", "NE"]
    assert sorted(g["name"] for g in c["field_tiles"]["regions"]) == ["Illinois", "Iowa", "Nebraska"]
    assert [s["postal"] for s in real.get("/v1/geo/states").json()["items"]] == ["IL", "IA", "NE"]
    assert real.get("/v1/geo/states/48/counties").status_code == 404
    assert real.get("/v1/geo/counties/48453").json()["has_field_coverage"] is False
