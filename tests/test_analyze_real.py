"""the real /ml/v1/analyze: every guarantee of docs/api_contract.md, the new crop_suitability, the three feature paths,
errors, and the response time of a precomputed field. no network: a synthetic POWER cell and a faked SDA are used."""
import copy
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import requests
from fastapi.testclient import TestClient

from ml_service import features, power_client, precomputed, soil_sda
from ml_service.main import app
from ml_service.real import DAYS

ROOT = Path(__file__).resolve().parent.parent
FLAGS = {"bare", "drought", "heat", "frost", "extreme_rain", "waterlogging"}
SCORE_KEYS = {"water", "soil_health", "nitrogen", "erosion", "income", "overall"}
LAT, LON = 41.9, -93.6
FAKE_SOIL = {"clay_pct": 27.0, "sand_pct": 12.0, "om_pct": 3.4, "soc_pct": 1.97, "ph_h2o": 6.4, "ec_ds_m": 0.3, "awc_cm_cm": 0.2,
             "kw_factor": 0.32, "hydgrp": "C", "drainage_class": "Somewhat poorly drained", "texture_class": "Silt loam",
             "slope_r": 3.0, "mukey": "123456", "mapunit_soil_pct": 100.0}


def synthetic_power(path: Path, seed: int = 0) -> None:
    """9 years of daily POWER-shaped data for a Corn Belt cell"""
    rng = np.random.default_rng(seed)
    days = pd.date_range("2017-01-01", "2025-12-31")
    doy = days.day_of_year.to_numpy()
    t = 10 + 15 * np.sin(2 * np.pi * (doy - 110) / 365) + rng.normal(0, 3, len(days))
    rain = np.where(rng.random(len(days)) < 0.33, rng.exponential(7, len(days)), 0.0)
    param = {
        "T2M": t, "T2M_MAX": t + 6 + rng.normal(0, 1, len(days)), "T2M_MIN": t - 6 + rng.normal(0, 1, len(days)),
        "PRECTOTCORR": rain, "RH2M": np.full(len(days), 70.0), "WS2M": np.full(len(days), 3.0),
        "ALLSKY_SFC_SW_DWN": 15 + 8 * np.sin(2 * np.pi * (doy - 80) / 365),
    }
    keys = days.strftime("%Y%m%d")
    path.write_text(json.dumps({"properties": {"parameter": {k: dict(zip(keys, map(float, v))) for k, v in param.items()}}}))


@pytest.fixture(autouse=True)
def real_mode(monkeypatch, tmp_path):
    """real mode, an empty precomputed folder, a private POWER cache with one synthetic cell, and no network"""
    monkeypatch.setenv("ML_MODE", "real")
    monkeypatch.setenv("ML_PRECOMPUTED_DIR", str(tmp_path / "pre"))
    monkeypatch.setenv("ML_POWER_CACHE_DIR", str(tmp_path / "power"))
    monkeypatch.setenv("ML_LINA_DIR", str(tmp_path / "lina"))
    (tmp_path / "power").mkdir()
    synthetic_power(power_client.cell_path(LAT, LON))
    monkeypatch.setattr(soil_sda, "fetch_soil", lambda lat, lon: dict(FAKE_SOIL))
    precomputed.clear_cache()
    return tmp_path


client = TestClient(app)


def history(last_soy=True):
    return [{"year": y, "crop": "corn" if (y % 2 == 0) == last_soy else "soybean", "cdl_code": 1 if (y % 2 == 0) == last_soy else 5}
            for y in range(2018, 2026)]


def body(**kw):
    b = {"request_id": "r-1", "field": {"field_id": "t-field-1", "centroid": {"lat": LAT, "lon": LON}, "admin": {"state": "IA"},
                                        "crop_history": history()},
         "options": {"n_strategies": 3, "language": "en"}}
    for path, value in kw.items():
        node = b
        *parents, last = path.split(".")
        for p in parents:
            node = node[p]
        node[last] = value
    return b


def post(b):
    return client.post("/ml/v1/analyze", json=b)


def assert_error(r, status, code):
    assert r.status_code == status, r.text
    e = r.json()["error"]
    assert e["code"] == code and e["message"] and isinstance(e["details"], dict)
    return e


# ---------------------------------------------------------------- the guarantees of the contract

def test_contract_guarantees():
    r = post(body())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["request_id"] == "r-1" and j["field_id"] == "t-field-1" and j["model_version"] == "0.2.0" and j["generated_at"].endswith("Z")
    assert j["feature_source"] == "on_the_fly" and j["disclaimer"]

    # strategies[0] is the current rotation, then exactly n alternatives sorted by the priority-weighted overall
    s = j["strategies"]
    assert s[0]["id"] == "current" and s[0]["is_current"] is True and s[0]["delta_vs_current"] is None
    assert len(s) == 4 and [x["is_current"] for x in s[1:]] == [False] * 3
    overall = [x["scores"]["overall"] for x in s[1:]]
    assert overall == sorted(overall, reverse=True)
    for x in s:
        assert set(x["scores"]) == SCORE_KEYS and all(0 <= v <= 100 for v in x["scores"].values())          # all 6 keys
        assert set(x["metrics"]) == {"water_use_mm_yr", "n_fixed_kg_ha_yr", "bare_days_yr", "erosion_t_ha_yr"}
        assert x["why"] and 0 <= x["confidence"] <= 1
        assert {c["season"] for c in x["sequence"]} <= {"main", "cover"} and all(c["year"] >= 1 for c in x["sequence"])
    for x in s[1:]:
        assert set(x["delta_vs_current"]) == SCORE_KEYS
        assert all(x["delta_vs_current"][k] == x["scores"][k] - s[0]["scores"][k] for k in SCORE_KEYS)

    # 12 months in order
    tl = j["vulnerability_timeline"]
    assert [m["month"] for m in tl] == list(range(1, 13))
    for m in tl:
        for k in ("bare_soil", "moisture_deficit", "heat_stress", "frost_risk", "extreme_precip"):
            assert 0 <= m[k] <= 1
        assert set(m["flags"]) <= FLAGS and m["bare_soil_source"] == "crop_calendar"

    # every source_id references a source, and only used sources are listed
    ids = {x["id"] for x in j["sources"]}
    refs = [k["source_ids"] for k in j["summary"]["key_numbers"]] + [e["source_ids"] for x in s for e in x["evidence"]]
    assert all(set(r_) <= ids for r_ in refs)
    assert ids == {"csb", "power", "ssurgo"}                                                  # no NDVI / SMAP / NASADEM yet
    assert j["summary"]["overall_risk"] in {"low", "medium", "high"} and len(j["summary"]["key_numbers"]) == 3

    # partial, with the reasons
    assert j["status"] == "partial"
    text = " ".join(j["warnings"])
    assert "NDVI" in text and "SMAP" in text and "TWI" in text
    assert j["detected_rotation"]["sequence"] == ["corn", "soybean"] and j["detected_rotation"]["source"] == "csb"
    assert j["detected_rotation"]["years_used"] == [2018, 2025] and j["detected_rotation"]["cycle_years"] == 2
    assert j["score_notes"]["income"].startswith("income_index")


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_exactly_n_alternatives(n):
    j = post(body(**{"options.n_strategies": n})).json()
    assert len(j["strategies"]) == n + 1


def test_crop_suitability():
    j = post(body(**{"field.soil": {"organic_matter_pct": 3.4}})).json()
    cs = j["crop_suitability"]
    assert len(cs) == 8 and [c["rank"] for c in cs] == list(range(1, 9))
    assert {c["crop"] for c in cs} == {"corn", "soybean", "winter_wheat", "sorghum", "alfalfa", "oats", "barley", "cereal_rye"}
    keys = {"crop", "name", "group", "fit_score", "next_year_share", "rank", "blocked", "block_reasons", "explanation",
            "top_factors", "top3_role", "model_class", "role", "parts"}
    for c in cs:
        assert set(c) == keys and 0 <= c["fit_score"] <= 100 and 0 <= c["next_year_share"] <= 100 and c["explanation"]
        assert c["group"] in {"cereal", "legume", "other"}
        assert (c["blocked"] and c["next_year_share"] == 0 and c["block_reasons"]) or not c["blocked"]
    assert cs[0]["crop"] == "corn" and len(cs[0]["top_factors"]) == 3                                    # corn after soybean
    shares = [c["next_year_share"] for c in cs if not c["blocked"]]
    assert sum(shares) == pytest.approx(100.0, abs=1e-6)                                                   # adds up to 100
    assert [c["next_year_share"] for c in cs] == sorted([c["next_year_share"] for c in cs], reverse=True)   # rank follows the share
    blocked_at_end = [c["blocked"] for c in cs]
    assert blocked_at_end == sorted(blocked_at_end)                                                      # blocked crops last
    assert next(c for c in cs if c["role"] == "cover")["next_year_share"] == 0
    roles = [c["top3_role"] for c in cs if c["top3_role"]]
    assert len(roles) == 3
    assert next(c for c in cs if c["crop"] == "cereal_rye")["role"] == "cover"
    assert next(c for c in cs if c["crop"] == "oats")["model_class"] is False


def test_timeline_reads_the_climate_normal():
    j = post(body()).json()
    tl = j["vulnerability_timeline"]
    assert tl[0]["frost_risk"] > 0.5 and tl[6]["frost_risk"] == 0.0 and tl[0]["heat_stress"] == 0.0     # January frosts, July none
    assert tl[6]["moisture_deficit"] > tl[0]["moisture_deficit"]                                          # summer is thirstier
    assert "frost" in tl[0]["flags"] and "bare" in tl[0]["flags"]
    kn = {k["id"]: k for k in j["summary"]["key_numbers"]}
    assert kn["bare_days"]["value"] == round(sum(m["bare_soil"] * DAYS[i] for i, m in enumerate(tl)))     # same numbers as the timeline
    assert kn["bare_days"]["value"] == pytest.approx(j["strategies"][0]["metrics"]["bare_days_yr"], abs=2)  # and as the calculator
    assert j["summary"]["headline"].startswith("Field is bare ~")


def test_scenario_changes_the_answer():
    base, hot = post(body()).json(), post(body(**{"scenario": {"temp_delta_c": 3.0, "precip_change_pct": -30}})).json()
    num = lambda j, k: next(x["value"] for x in j["summary"]["key_numbers"] if x["id"] == k)
    assert num(hot, "heat_days") > num(base, "heat_days") and num(hot, "jul_aug_water_deficit") > num(base, "jul_aug_water_deficit")
    assert hot["strategies"][0]["scores"]["water"] < base["strategies"][0]["scores"]["water"]
    assert hot["strategies"][0]["metrics"]["water_use_mm_yr"] > base["strategies"][0]["metrics"]["water_use_mm_yr"]


def test_priorities_matter():
    a = post(body(priorities={"water": 0, "soil_health": 0, "nitrogen": 0, "erosion": 1, "income": 0})).json()
    b = post(body(priorities={"water": 0, "soil_health": 0, "nitrogen": 0, "erosion": 0, "income": 1})).json()
    assert [s["scores"]["overall"] for s in a["strategies"]] != [s["scores"]["overall"] for s in b["strategies"]]


def test_farmer_input():
    j = post(body(**{"farmer_input": {"current_rotation": ["corn", "corn", "soybean"], "excluded_crops": ["sorghum", "alfalfa"],
                                      "irrigated": True, "has_livestock": False}})).json()
    assert j["detected_rotation"]["source"] == "farmer_input" and j["detected_rotation"]["sequence"] == ["corn", "corn", "soybean"]
    used = {c["crop"] for s in j["strategies"][1:] for c in s["sequence"]}
    assert not used & {"sorghum", "alfalfa"}
    cs = {c["crop"]: c for c in j["crop_suitability"]}
    assert cs["sorghum"]["blocked"] and any("farmer" in r or "фермер" in r for r in cs["sorghum"]["block_reasons"])
    assert cs["sorghum"]["next_year_share"] == 0 and cs["sorghum"]["fit_score"] >= 0                      # the field still suits it
    assert not {c["crop"] for c in j["crop_suitability"] if c["top3_role"]} & {"sorghum", "alfalfa"}
    assert sum(c["next_year_share"] for c in j["crop_suitability"] if not c["blocked"]) == pytest.approx(100.0, abs=1e-6)
    assert all(c["rank"] > cs["corn"]["rank"] for c in (cs["sorghum"], cs["alfalfa"]))


def test_ukrainian_texts():
    j = post(body(**{"options": {"n_strategies": 3, "language": "uk"}})).json()
    assert j["strategies"][0]["name"].startswith("Поточна: Кукурудза") and j["summary"]["headline"].startswith("Поле голе")
    assert "NDVI" in " ".join(j["warnings"]) and j["crop_suitability"][0]["name"] == "Кукурудза"


def test_request_soil_overrides_and_organic_soil_warning():
    j = post(body(**{"field.soil": {"organic_matter_pct": 35}})).json()
    assert any("organic soil" in w for w in j["warnings"])


@pytest.mark.skipif(not (ROOT / "data/precomputed").exists() or not list((ROOT / "data/precomputed").glob("*.parquet")),
                    reason="needs a precomputed county (scripts/09_precompute_region.py)")
def test_high_fit_but_not_on_top_is_explained(monkeypatch):
    """soybean after soybean: the field suits it (high fit_score) but the advice for next year is corn, and it says why"""
    monkeypatch.undo()
    monkeypatch.setenv("ML_MODE", "real")
    precomputed.clear_cache()
    idx = precomputed._index(str(precomputed.directory()))
    rec = next(r for r in idx.values() if r["hist_2025"] == 5 and r["hist_2024"] == 1 and r["hist_2023"] == 5 and r["state"] == "IA" and r["om_pct"] < 8)
    b = {"field": {"field_id": rec["field_id"], "centroid": {"lat": rec["lat"], "lon": rec["lon"]}, "admin": {"state": "IA"}}}
    for lang, word in (("en", "last year was already"), ("uk", "торік уже була")):
        b["options"] = {"language": lang}
        cs = {c["crop"]: c for c in TestClient(app).post("/ml/v1/analyze", json=b).json()["crop_suitability"]}
        assert cs["corn"]["rank"] == 1 and cs["soybean"]["rank"] == 2
        assert cs["soybean"]["fit_score"] >= 40 and cs["soybean"]["next_year_share"] < 10
        assert word in cs["soybean"]["explanation"]
        assert cs["winter_wheat"]["fit_score"] < 10                                                      # not suited here at all


# ---------------------------------------------------------------- the three feature paths and errors

def test_on_the_fly_needs_history_or_a_cache_hit():
    b = body()
    del b["field"]["crop_history"]
    e = assert_error(post(b), 422, "INVALID_INPUT")
    assert e["details"]["field"] == "field.crop_history"


def test_out_of_coverage_and_validation_errors():
    assert_error(post(body(**{"field.admin.state": "TX"})), 404, "OUT_OF_COVERAGE")
    assert_error(post(body(**{"scenario": {"temp_delta_c": 9, "precip_change_pct": 0}})), 422, "INVALID_INPUT")
    assert_error(post(body(**{"farmer_input": {"current_rotation": ["corn", "banana"]}})), 422, "INVALID_INPUT")
    assert_error(post(body(**{"farmer_input": {"current_rotation": ["corn", "cereal_rye"]}})), 422, "INVALID_INPUT")


def test_missing_power_cell_is_503_and_keeps_downloading(monkeypatch, tmp_path):
    def down(*a, **k):
        raise requests.ConnectionError("no network")
    monkeypatch.setattr(power_client, "_download", down)
    e = assert_error(post(body(**{"field.centroid": {"lat": 38.2, "lon": -97.4}, "field.admin.state": "KS"})), 503, "DATA_UNAVAILABLE")
    assert e["details"]["retry_after_s"] == 60 and "cell" in e["details"]


def test_soil_service_down_is_503(monkeypatch):
    from ml_service.errors import data_unavailable
    def boom(lat, lon):
        raise data_unavailable("Soil data service (USDA SDA) is not available right now.")
    monkeypatch.setattr(soil_sda, "fetch_soil", boom)
    assert_error(post(body()), 503, "DATA_UNAVAILABLE")


def test_no_ssurgo_soil_uses_defaults_with_a_warning(monkeypatch):
    monkeypatch.setattr(soil_sda, "fetch_soil", lambda lat, lon: None)
    j = post(body()).json()
    assert j["status"] == "partial" and any("regional defaults" in w for w in j["warnings"])


def test_precomputed_county_file_is_used(tmp_path):
    """a county file is read without any external call (the faked SDA would otherwise answer)"""
    snap = power_client.snap_to_cell(LAT, LON)
    cell = power_client.cell_key(*snap)
    from ml_service import season_climate
    clim = season_climate.field_climate(season_climate.load_daily(str(power_client.cell_path(LAT, LON)), snap[0]), 2025)
    soil = dict(FAKE_SOIL, ph_h2o=5.2)                     # a marker: acid soil blocks alfalfa
    meta = {"field_id": "pre-1", "state": "IA", "county_fips5": "19153", "lat": LAT, "lon": LON, "area_ha": 40.0, "csb_acres": 99.0}
    row = precomputed.build_row(meta, {y: (1 if y % 2 == 0 else 5) for y in range(2018, 2026)}, soil, clim, cell)
    (tmp_path / "pre").mkdir()
    pd.DataFrame([row]).to_parquet(tmp_path / "pre" / "19153.parquet", index=False)
    precomputed.clear_cache()
    b = body(**{"field.field_id": "pre-1"})
    del b["field"]["crop_history"]
    j = post(b).json()
    assert j["feature_source"] == "precomputed" and j["detected_rotation"]["sequence"] == ["corn", "soybean"]
    assert next(c for c in j["crop_suitability"] if c["crop"] == "alfalfa")["blocked"]


def test_ndvi_switches_bare_soil_to_landsat(tmp_path):
    lina = tmp_path / "lina"
    lina.mkdir()
    rows = [("t-field-1", y, m, 0.15 if m in (4, 10) else 0.7, 3) for y in (2024, 2025) for m in range(4, 11)]
    pd.DataFrame(rows, columns=["field_id", "year", "month", "ndvi_mean", "n_obs"]).to_csv(lina / "ndvi_monthly.csv", index=False)
    j = post(body()).json()
    src = {m["month"]: m["bare_soil_source"] for m in j["vulnerability_timeline"]}
    assert src[4] == src[7] == src[10] == "landsat_ndvi" and src[1] == "crop_calendar"
    assert next(m for m in j["vulnerability_timeline"] if m["month"] == 4)["bare_soil"] == 1.0
    assert next(m for m in j["vulnerability_timeline"] if m["month"] == 7)["bare_soil"] == 0.0
    assert "landsat_ndvi" in {s["id"] for s in j["sources"]} and not any("No Landsat NDVI" in w for w in j["warnings"])


# ---------------------------------------------------------------- mode switch and speed

def test_mock_mode_is_still_available(monkeypatch):
    monkeypatch.setenv("ML_MODE", "mock")
    assert client.get("/ml/health").json()["model_version"] == "0.1.0-mock"
    j = post(body()).json()
    assert j["model_version"] == "0.1.0-mock" and "crop_suitability" not in j
    monkeypatch.setenv("ML_MODE", "real")
    h = client.get("/ml/health").json()
    assert h["mode"] == "real" and h["model_version"] == "0.2.0" and h["coverage"]["states"] == ["IA", "IL", "NE", "KS"]
    crops = {c["crop"]: c for c in client.get("/ml/v1/meta/crops").json()["crops"]}
    assert set(crops) >= {"corn", "barley", "cereal_rye"} and crops["cereal_rye"]["type"] == "cover" and crops["corn"]["cdl_code"] == 1


@pytest.mark.skipif(not (ROOT / "data/features/climate_season.parquet").exists(), reason="needs data/ (not in git)")
def test_sample_field_is_fast_and_uses_the_tables(monkeypatch):
    monkeypatch.undo()                                           # the real data folders for this test
    monkeypatch.setenv("ML_MODE", "real")
    precomputed.clear_cache()
    b = {"field": {"field_id": "191825002125636", "centroid": {"lat": 41.81, "lon": -91.0}, "admin": {"state": "IA"}}}
    with TestClient(app) as c:                                   # lifespan loads the model and tables
        times = []
        for _ in range(3):
            t0 = time.time()
            r = c.post("/ml/v1/analyze", json=b)
            times.append(time.time() - t0)
        j = r.json()
    assert r.status_code == 200 and j["feature_source"] == "tables" and j["detected_rotation"]["label"] == "Corn – Soybean"
    assert max(times) < 2.0, times


@pytest.mark.skipif(not (ROOT / "data/precomputed").exists() or not list((ROOT / "data/precomputed").glob("*.parquet")),
                    reason="needs a precomputed county (scripts/09_precompute_region.py)")
def test_precomputed_field_answers_in_under_two_seconds(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setenv("ML_MODE", "real")
    precomputed.clear_cache()
    rec = next(iter(precomputed._index(str(precomputed.directory())).values()))
    b = {"field": {"field_id": rec["field_id"], "centroid": {"lat": rec["lat"], "lon": rec["lon"]}, "admin": {"state": rec["state"]}}}
    with TestClient(app) as c:
        times = []
        for _ in range(3):
            t0 = time.time()
            r = c.post("/ml/v1/analyze", json=b)
            times.append(time.time() - t0)
    assert r.status_code == 200 and r.json()["feature_source"] == "precomputed"
    assert max(times) < 2.0, times
