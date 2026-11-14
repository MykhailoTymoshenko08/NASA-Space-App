"""contract tests for the mock ml service. run: pytest -q"""
import copy

import pytest
from fastapi.testclient import TestClient

from ml_service import analyze as analyze_mod
from ml_service.errors import data_unavailable
from ml_service.main import app

client = TestClient(app)
# unhandled exceptions must come back as the contract 500 json, not be re-raised into the test
client_500 = TestClient(app, raise_server_exceptions=False)

SCORE_KEYS = {"water", "soil_health", "nitrogen", "erosion", "income", "overall"}
FLAGS = {"bare", "drought", "heat", "frost", "extreme_rain", "waterlogging"}

BASE = {
    "request_id": "b1f2c3d4-test",
    "field": {
        "field_id": "191825000000212",
        "geometry": {"type": "Polygon", "coordinates": [[[-93.62, 41.59], [-93.61, 41.59], [-93.61, 41.60],
                                                          [-93.62, 41.60], [-93.62, 41.59]]]},
        "centroid": {"lat": 41.595, "lon": -93.615},
        "area_ha": 64.7,
        "admin": {"country": "US", "state": "IA", "state_fips": "19", "county_fips": "19153"},
        "crop_history": [{"year": y, "crop": "corn" if y % 2 == 0 else "soybean"} for y in range(2018, 2026)],
        "soil": {"texture": "silty clay loam", "organic_matter_pct": 3.4, "drainage_class": "poorly drained",
                 "hydrologic_group": "C/D", "awc_cm_cm": 0.21, "slope_pct": 2.1},
    },
    "priorities": {"water": 0.8, "soil_health": 0.6, "nitrogen": 0.5, "erosion": 0.4, "income": 0.7},
    "scenario": {"temp_delta_c": 0.0, "precip_change_pct": 0},
    "farmer_input": {"irrigated": None, "current_rotation": None, "excluded_crops": [], "has_livestock": None},
    "options": {"n_strategies": 3, "language": "en", "include_monthly_series": False},
}


def make(**patch):
    """deep copy of BASE with dotted-path overrides, e.g. make(**{"options.n_strategies": 2})"""
    body = copy.deepcopy(BASE)
    for path, value in patch.items():
        node = body
        *parents, last = path.split(".")
        for p in parents:
            node = node[p]
        node[last] = value
    return body


def post(body):
    return client.post("/ml/v1/analyze", json=body)


def assert_error(resp, status, code):
    assert resp.status_code == status, resp.text
    err = resp.json()["error"]
    assert err["code"] == code
    assert isinstance(err["message"], str) and err["message"]
    assert isinstance(err["details"], dict)
    return err


# ---------------------------------------------------------------- health / meta

def test_health():
    r = client.get("/ml/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_version"]
    assert body["coverage"] == {"states": ["IA", "IL", "NE", "KS"], "years": [2018, 2025]}


def test_crops_meta():
    r = client.get("/ml/v1/meta/crops")
    assert r.status_code == 200
    crops = {c["crop"]: c for c in r.json()["crops"]}
    assert crops["corn"]["cdl_code"] == 1 and crops["corn"]["type"] == "cash"
    assert crops["soybean"]["cdl_code"] == 5 and crops["soybean"]["type"] == "legume"
    assert crops["cereal_rye"]["cdl_code"] == 27 and crops["cereal_rye"]["type"] == "cover"
    for c in crops.values():
        assert set(c) == {"crop", "cdl_code", "name_en", "name_uk", "type"}


# ---------------------------------------------------------------- analyze: valid response

def test_valid_response_shape_and_guarantees():
    r = post(make())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["request_id"] == "b1f2c3d4-test"
    assert body["field_id"] == "191825000000212"
    assert body["status"] == "ok"
    assert body["generated_at"].endswith("Z")
    assert body["disclaimer"]

    rot = body["detected_rotation"]
    assert rot["sequence"] == ["soybean", "corn"] or rot["sequence"] == ["corn", "soybean"]
    assert rot["source"] == "csb" and rot["years_used"] == [2018, 2025]
    assert 0 <= rot["confidence"] <= 1

    tl = body["vulnerability_timeline"]
    assert [t["month"] for t in tl] == list(range(1, 13))
    for t in tl:
        for k in ("bare_soil", "moisture_deficit", "heat_stress", "frost_risk", "extreme_precip"):
            assert 0 <= t[k] <= 1
        assert set(t["flags"]) <= FLAGS

    source_ids = {s["id"] for s in body["sources"]}
    assert {"landsat_ndvi", "smap", "power", "nasadem", "csb", "ssurgo"} <= source_ids
    refs = [k["source_ids"] for k in body["summary"]["key_numbers"]]
    for s in body["strategies"]:
        refs += [e["source_ids"] for e in s["evidence"]]
    assert all(set(r_) <= source_ids for r_ in refs)
    assert body["summary"]["overall_risk"] in {"low", "medium", "high"}


def test_strategies_current_first_and_sorted():
    body = post(make()).json()
    strategies = body["strategies"]
    assert strategies[0]["id"] == "current" and strategies[0]["is_current"] is True
    assert strategies[0]["delta_vs_current"] is None
    alts = strategies[1:]
    assert all(not s["is_current"] for s in alts)
    overalls = [s["scores"]["overall"] for s in alts]
    assert overalls == sorted(overalls, reverse=True)
    cur = strategies[0]["scores"]
    for s in alts:
        assert set(s["scores"]) == SCORE_KEYS
        assert set(s["delta_vs_current"]) == SCORE_KEYS
        for k in SCORE_KEYS:
            assert s["delta_vs_current"][k] == s["scores"][k] - cur[k]
        assert s["why"] and s["evidence"] and s["benefits"] and s["risks"] and s["check_with_agronomist"]
        assert 0 <= s["confidence"] <= 1
        assert set(s["metrics"]) == {"water_use_mm_yr", "n_fixed_kg_ha_yr", "bare_days_yr", "erosion_t_ha_yr"}
        assert {i["season"] for i in s["sequence"]} <= {"main", "cover"}


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_exactly_n_alternatives(n):
    body = post(make(**{"options.n_strategies": n})).json()
    assert len(body["strategies"]) == n + 1


def test_default_options_priorities_and_scenario():
    body = make()
    for key in ("priorities", "scenario", "farmer_input", "options", "request_id"):
        body.pop(key)
    r = post(body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out["strategies"]) == 4  # default n_strategies = 3 + current
    assert out["request_id"]  # generated when missing


def test_deterministic_for_same_input():
    a, b = post(make()).json(), post(make()).json()
    a.pop("generated_at"), b.pop("generated_at")
    assert a == b


def test_uk_language():
    body = post(make(**{"options.language": "uk"})).json()
    assert body["strategies"][0]["name"].startswith("Поточна")
    assert "Decision-support" not in body["disclaimer"]


def test_missing_history_and_soil_gives_partial():
    body = make()
    body["field"].pop("crop_history")
    body["field"].pop("soil")
    out = post(body).json()
    assert out["status"] == "partial"
    assert out["warnings"]
    assert out["detected_rotation"]["source"] == "model_prior"
    assert len(out["strategies"]) == 4


def test_farmer_rotation_overrides_detection():
    out = post(make(**{"farmer_input.current_rotation": ["corn", "corn", "soybean"]})).json()
    assert out["detected_rotation"]["source"] == "farmer_input"
    assert out["detected_rotation"]["sequence"] == ["corn", "corn", "soybean"]


def test_excluded_crops_are_not_suggested():
    # the pool has 6 candidates; dropping alfalfa and rye removes 3 (rye, rye-vetch mix, perennial)
    out = post(make(**{"farmer_input.excluded_crops": ["alfalfa", "cereal_rye"], "options.n_strategies": 3})).json()
    used = {i["crop"] for s in out["strategies"][1:] for i in s["sequence"]}
    assert not used & {"alfalfa", "cereal_rye"}
    assert len(out["strategies"]) == 4
    assert out["status"] == "ok"


def test_fewer_alternatives_than_requested_is_partial():
    excl = ["corn", "soybean", "alfalfa", "cereal_rye", "hairy_vetch", "sorghum", "winter_wheat", "oats"]
    out = post(make(**{"farmer_input.excluded_crops": excl, "options.n_strategies": 5})).json()
    assert out["status"] == "partial"
    assert len(out["strategies"]) < 6


# ---------------------------------------------------------------- sliders must matter

def test_priorities_change_ranking_or_overall():
    erosion_first = make(priorities={"water": 0, "soil_health": 0, "nitrogen": 0, "erosion": 1, "income": 0})
    income_first = make(priorities={"water": 0, "soil_health": 0, "nitrogen": 0, "erosion": 0, "income": 1})
    a, b = post(erosion_first).json(), post(income_first).json()
    # the same alternative is scored differently when priorities flip
    assert a["strategies"][1]["scores"]["overall"] != b["strategies"][1]["scores"]["overall"]
    assert a["strategies"][0]["scores"]["overall"] == a["strategies"][0]["scores"]["erosion"]
    assert b["strategies"][0]["scores"]["overall"] == b["strategies"][0]["scores"]["income"]
    # the best alternative under "erosion only" is not worse on erosion than under "income only"
    assert a["strategies"][1]["scores"]["erosion"] >= b["strategies"][1]["scores"]["erosion"]


def test_all_zero_priorities_use_equal_weights():
    body = make(priorities={k: 0 for k in ("water", "soil_health", "nitrogen", "erosion", "income")})
    out = post(body).json()
    cur = out["strategies"][0]["scores"]
    expected = round(sum(cur[k] for k in SCORE_KEYS - {"overall"}) / 5)
    assert abs(cur["overall"] - expected) <= 1


def test_scenario_moves_scores_and_timeline():
    base = post(make()).json()
    hot_dry = post(make(**{"scenario.temp_delta_c": 3.0, "scenario.precip_change_pct": -30})).json()
    wet = post(make(**{"scenario.precip_change_pct": 20})).json()
    b, h, w = (x["strategies"][0]["scores"] for x in (base, hot_dry, wet))
    assert h["water"] < b["water"] < w["water"]
    assert h["income"] < b["income"]
    assert h["overall"] < b["overall"]
    heat = lambda x: next(k for k in x["summary"]["key_numbers"] if k["id"] == "heat_days")["value"]
    assert heat(hot_dry) > heat(base)
    deficit = lambda x: max(t["moisture_deficit"] for t in x["vulnerability_timeline"])
    assert deficit(hot_dry) > deficit(base)


def test_irrigation_and_livestock_inputs_matter():
    dry = {"scenario.precip_change_pct": -30}
    no_irr = post(make(**dry)).json()["strategies"][0]["scores"]["water"]
    irr = post(make(**dry, **{"farmer_input.irrigated": True})).json()["strategies"][0]["scores"]["water"]
    assert irr > no_irr


# ---------------------------------------------------------------- bounds -> 422

@pytest.mark.parametrize("patch", [
    {"priorities.water": 1.1},
    {"priorities.income": -0.1},
    {"scenario.temp_delta_c": 4.5},
    {"scenario.temp_delta_c": -2.5},
    {"scenario.precip_change_pct": 25},
    {"scenario.precip_change_pct": -41},
    {"options.n_strategies": 0},
    {"options.n_strategies": 6},
    {"options.language": "de"},
    {"field.centroid": {"lat": 91, "lon": 0}},
    {"field.area_ha": 0},
    {"field.soil.awc_cm_cm": 2},
    {"field.admin.state": "Iowa"},
    {"field.field_id": ""},
])
def test_out_of_bounds_values_are_422(patch):
    err = assert_error(post(make(**patch)), 422, "INVALID_INPUT")
    assert err["details"]["errors"]


def test_boundary_values_are_accepted():
    ok = make(**{"scenario.temp_delta_c": 4, "scenario.precip_change_pct": -40,
                 "priorities.water": 1, "priorities.income": 0})
    assert post(ok).status_code == 200
    ok = make(**{"scenario.temp_delta_c": -2, "scenario.precip_change_pct": 20})
    assert post(ok).status_code == 200


def test_unclosed_ring_and_swapped_coords_are_422():
    bad_ring = make(**{"field.geometry": {"type": "Polygon", "coordinates": [[[-93.6, 41.5], [-93.5, 41.5],
                                                                              [-93.5, 41.6], [-93.6, 41.6]]]}})
    assert_error(post(bad_ring), 422, "INVALID_INPUT")
    swapped = make(**{"field.geometry": {"type": "Polygon", "coordinates": [[[41.5, -93.6], [41.5, -93.5],
                                                                             [41.6, -93.5], [41.6, -93.6],
                                                                             [41.5, -93.6]]]}})
    assert_error(post(swapped), 422, "INVALID_INPUT")


def test_missing_required_fields_are_422():
    body = make()
    body["field"].pop("admin")
    assert_error(post(body), 422, "INVALID_INPUT")
    body = make()
    body["field"].pop("geometry")
    body["field"].pop("centroid")
    assert_error(post(body), 422, "INVALID_INPUT")
    assert_error(post({}), 422, "INVALID_INPUT")


def test_centroid_alone_is_enough():
    body = make()
    body["field"].pop("geometry")
    assert post(body).status_code == 200


def test_unknown_key_and_bad_json_are_422():
    assert_error(post(make(**{"priorities.drought": 0.5})), 422, "INVALID_INPUT")
    r = client.post("/ml/v1/analyze", content="{not json", headers={"content-type": "application/json"})
    assert_error(r, 422, "INVALID_INPUT")


def test_unknown_crop_in_farmer_rotation_is_422():
    assert_error(post(make(**{"farmer_input.current_rotation": ["corn", "banana"]})), 422, "INVALID_INPUT")


# ---------------------------------------------------------------- 404 / 500 / 503

def test_out_of_coverage_is_404():
    err = assert_error(post(make(**{"field.admin.state": "TX"})), 404, "OUT_OF_COVERAGE")
    assert err["details"]["state"] == "TX"


def test_state_is_case_insensitive():
    assert post(make(**{"field.admin.state": "ia"})).status_code == 200


def test_unknown_route_uses_error_format():
    r = client.get("/ml/v1/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_unexpected_exception_is_500(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("boom")
    monkeypatch.setattr(analyze_mod, "evaluate", boom)
    r = client_500.post("/ml/v1/analyze", json=make())
    assert_error(r, 500, "INTERNAL")
    assert "boom" not in r.text  # internals are not leaked


def test_data_unavailable_is_503(monkeypatch):
    def down(*_a, **_k):
        raise data_unavailable("SMAP not precomputed for this field")
    monkeypatch.setattr(analyze_mod, "build_timeline", down)
    assert_error(post(make()), 503, "DATA_UNAVAILABLE")


# ---------------------------------------------------------------- cors

def test_cors_preflight_and_headers():
    r = client.options("/ml/v1/analyze", headers={
        "origin": "http://localhost:5173", "access-control-request-method": "POST",
        "access-control-request-headers": "content-type"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    r = client.get("/ml/health", headers={"origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "*"
