"""Real ML engine wiring, request translation, upstream failures and frontend contract compatibility."""

import copy
import json

import httpx
import pytest
import respx

from app.analyses.ml import ml_request
from app.core.config import REPO_DIR, Settings
from app.models import AnalysisOptions, CropYear, FieldSelection
from tests.contract import assert_matches_contract
from tests.test_analyses import F1, F2, wait_done
from tests.test_snapshots import mock_all

pytestmark = pytest.mark.contract
ML_URL = "http://ml.test:8001/ml/v1/analyze"


@pytest.fixture
def ml_client(make_client, data_dir):
    return make_client(data_dir, analysis_engine="ml", ml_base_url="http://ml.test:8001",
                       stub_fail_rate=1.0)


@pytest.fixture
def upstream():
    with respx.mock(assert_all_called=False) as router:
        mock_all(router)
        yield router.post(ML_URL)


def respond(route, example="polk", change=None):
    data = json.loads((REPO_DIR / f"ml/docs/examples/analyze_response_{example}.json").read_text())
    replies = []

    def handler(request):
        payload = json.loads(request.content)
        reply = copy.deepcopy(data)
        reply.update(field_id=payload["field"]["field_id"], request_id=payload["request_id"])
        if change:
            change(reply)
        replies.append(reply)
        return httpx.Response(200, json=reply)

    route.mock(side_effect=handler)
    return replies


def analyze(client, selection=F1, **options):
    created = client.post("/v1/analyses", json={"selection": selection, "options": options})
    assert created.status_code == 202, created.text
    assert_matches_contract(created)
    return wait_done(client, created.json()["job_id"]).json()


@pytest.mark.parametrize("example", ["polk", "reno"])
def test_ml_results_fit_existing_frontend_contract(ml_client, upstream, example):
    replies = respond(upstream, example)
    job = analyze(ml_client, priorities=["soil_health", "water_conservation"], horizon_years=4)
    assert job["status"] == "succeeded", job
    result = job["result"]
    assert result["ml_analysis"] == replies[0]
    assert result["model_version"] == "0.2.0"
    assert result["selection"]["field_id"] == F1["field_id"]
    assert result["current_conditions"]
    assert result["time_series"] == []  # monthly climate normals are not historical measurements
    strategies = result["strategies"]
    assert sum(s["is_current"] for s in strategies) == 1
    assert [s["score"] for s in strategies] == sorted((s["score"] for s in strategies), reverse=True)
    for strategy in strategies:
        raw = next(s for s in replies[0]["strategies"] if s["id"] == strategy["id"])
        assert strategy["score"] == raw["scores"]["overall"]
        assert {s["criterion"] for s in strategy["score_breakdown"]} == {
            "water_use", "soil_health", "nitrogen", "erosion", "income",
        }
        for index, season in enumerate(strategy["rotation"]):
            assert season["season_index"] == index
            if raw["sequence"][index]["season"] == "cover":
                assert season["role"] == "cover_crop"
    assert any("not a profit estimate" in w for w in result["warnings"])
    assert {s["name"] for s in replies[0]["sources"]} <= {s["dataset"] for s in result["datasets_used"]}
    payload = json.loads(upstream.calls.last.request.content)
    assert payload["field"]["field_id"] == "190000000001"
    assert payload["field"]["admin"] == {
        "country": "US", "state": "IA", "state_fips": "19", "county_fips": "19153",
    }
    assert payload["field"]["crop_history"] == [
        {"year": 2023, "crop": "corn", "cdl_code": 1},
        {"year": 2024, "crop": "soybean", "cdl_code": 5},
        {"year": 2025, "crop": "corn", "cdl_code": 1},
    ]
    assert payload["priorities"] == {"water": 1, "soil_health": 1, "nitrogen": 0.5,
                                     "erosion": 0.5, "income": 0.5}
    assert payload["options"] == {"n_strategies": 3, "language": "en", "horizon_years": 4}


def test_farmer_history_wins_and_special_cdl_codes_survive(ml_client, upstream):
    respond(upstream)
    history = [{"year": 2024, "crop": "Fallow/Idle Cropland"},
               {"year": 2025, "crop": "Dbl Crop WinWht/Soybeans"}]
    assert analyze(ml_client, crop_history=history)["status"] == "succeeded"
    rows = json.loads(upstream.calls.last.request.content)["field"]["crop_history"]
    assert rows == [{"year": 2024, "crop": "fallow", "cdl_code": 61},
                    {"year": 2025, "crop": "Dbl Crop WinWht/Soybeans", "cdl_code": 26}]


def test_partial_with_only_current_rotation_succeeds(ml_client, upstream):
    def only_current(data):
        data["strategies"] = [data["strategies"][0]]
        data["status"] = "partial"
        data["warnings"].append("No valid alternatives")
    respond(upstream, change=only_current)
    job = analyze(ml_client)
    assert job["status"] == "succeeded"
    assert len(job["result"]["strategies"]) == 1
    assert "No valid alternatives" in job["result"]["warnings"]


def test_buffered_point_and_unknown_history_are_not_invented(ml_client, upstream):
    respond(upstream)
    job = analyze(ml_client, selection={"point": {"lat": 41.70, "lon": -93.70}},
                  crop_history=[{"year": 2025, "crop": "Sunflower"}])
    assert job["status"] == "succeeded"
    payload = json.loads(upstream.calls.last.request.content)
    assert payload["field"]["field_id"].startswith("point:")
    assert payload["field"]["crop_history"] == [{"year": 2025, "crop": "Sunflower"}]
    assert any("500 m circle" in w for w in job["result"]["warnings"])


def test_no_history_leaves_ml_precomputed_detection_available(ml_client, upstream):
    respond(upstream)
    assert analyze(ml_client, selection=F2)["status"] == "succeeded"
    assert "crop_history" not in json.loads(upstream.calls.last.request.content)["field"]


def test_ml_jobs_include_budgets_without_converting_income_index_to_money(ml_client, upstream):
    respond(upstream)
    options = {"budget": {"land_rent_per_acre": 0, "cover_cost_per_acre": 40}}
    first = analyze(ml_client, **options)
    result = first["result"]
    current = next(s for s in result["strategies"] if s["is_current"])
    assert current["budget"]["status"] == "estimated"
    assert current["budget"]["delta_vs_current_per_acre"]["base"] == 0
    for s in result["strategies"]:
        assert s["budget"]["is_illustrative"]
        assert (s["budget"]["annual_average"] is None) == (s["budget"]["status"] != "estimated")
    payload = json.loads(upstream.calls.last.request.content)
    assert "budget" not in payload["options"]  # Backend cash assumptions do not alter ML's agronomic ranking.
    changed = analyze(ml_client, budget={"land_rent_per_acre": 50, "cover_cost_per_acre": 40})
    assert first["job_id"] != changed["job_id"]
    updated = next(s for s in changed["result"]["strategies"] if s["is_current"])
    assert (updated["budget"]["annual_average"]["base"]["cost_per_acre"]
            == current["budget"]["annual_average"]["base"]["cost_per_acre"] + 50)


def test_changing_only_ml_income_score_does_not_change_budget(ml_client, upstream):
    respond(upstream)
    first = analyze(ml_client)
    respond(upstream, change=lambda d: [s["scores"].update(income=1) for s in d["strategies"]])
    ml_client.app.state.services.analyses.dedupe_ttl_s = -1
    second = analyze(ml_client)
    a = {s["id"]: s["budget"] for s in first["result"]["strategies"]}
    assert {s["id"]: s["budget"] for s in second["result"]["strategies"]} == a


def test_short_ml_plan_cannot_report_a_complete_budget_for_a_longer_request(ml_client, upstream):
    respond(upstream)
    job = analyze(ml_client, horizon_years=5, budget={"land_rent_per_acre": 0, "cover_cost_per_acre": 40})
    assert job["status"] == "succeeded"
    for strategy in job["result"]["strategies"]:
        budget = strategy["budget"]
        assert budget["horizon_years"] == 5 and len(budget["years"]) == 5
        assert budget["status"] == "partial"
        assert budget["annual_average"] is budget["horizon_total"] is None
        assert budget["years"][3]["scenarios"] is budget["years"][4]["scenarios"] is None


def test_invalid_budget_request_returns_contract_validation_error(ml_client):
    response = ml_client.post("/v1/analyses", json={
        "selection": F1, "options": {"budget": {"land_rent_per_acre": -1}},
    })
    assert response.status_code == 422
    assert_matches_contract(response)


@pytest.mark.parametrize(("status", "ml_code", "backend_code", "retry"), [
    (422, "INVALID_INPUT", "VALIDATION_ERROR", False),
    (404, "OUT_OF_COVERAGE", "OUTSIDE_COVERAGE", False),
    (503, "DATA_UNAVAILABLE", "UPSTREAM_DATA_UNAVAILABLE", True),
    (500, "INTERNAL", "UPSTREAM_DATA_UNAVAILABLE", False),
])
def test_errors_fail_jobs_with_retry_guidance(ml_client, upstream, status, ml_code, backend_code, retry):
    upstream.respond(status, json={"error": {"code": ml_code, "message": "ML explanation",
                                             "details": {"field": "field.crop_history"}}})
    job = analyze(ml_client)
    assert job["status"] == "failed" and "result" not in job
    assert job["error"]["code"] == backend_code
    if status < 500:
        assert job["error"]["message"] == "ML explanation"
        assert job["error"]["details"] == {"field": "field.crop_history"}
    if retry:
        assert job["error"]["details"]["retry_after_s"] == 60
    if status == 500:
        assert "ML explanation" not in job["error"]["message"]


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
def test_network_failures_do_not_fall_back_to_demo_results(ml_client, upstream, error):
    upstream.mock(side_effect=error("unavailable"))
    job = analyze(ml_client)
    assert job["status"] == "failed" and "result" not in job
    assert job["error"]["code"] == "UPSTREAM_DATA_UNAVAILABLE"
    assert job["error"]["details"]["retry_after_s"] == 60


@pytest.mark.parametrize("change", [
    lambda d: d.update(field_id="wrong-field"),
    lambda d: d.update(request_id="wrong-request"),
    lambda d: d.update(strategies=[]),
    lambda d: d["strategies"][0].update(is_current=False),
    lambda d: d["strategies"][1].update(is_current=True),
    lambda d: d["strategies"][0]["scores"].update(overall=200),
    lambda d: d["strategies"][0].update(evidence=[{"text": "Bad source", "source_ids": ["missing"]}]),
])
def test_invalid_upstream_results_fail_cleanly(ml_client, upstream, change):
    respond(upstream, change=change)
    job = analyze(ml_client)
    assert job["status"] == "failed" and job["error"]["code"] == "UPSTREAM_DATA_UNAVAILABLE"


def test_retry_after_upstream_failure_creates_a_new_job(ml_client, upstream):
    upstream.respond(503, json={"error": {"code": "DATA_UNAVAILABLE", "message": "Not ready"}})
    first = analyze(ml_client)
    respond(upstream)
    second = analyze(ml_client)
    assert first["job_id"] != second["job_id"] and second["status"] == "succeeded"
    third = analyze(ml_client)
    assert second["job_id"] == third["job_id"]
    assert upstream.call_count == 2


def test_ml_is_default_and_stub_requires_explicit_choice():
    assert Settings(_env_file=None).analysis_engine == "ml"


def test_empty_farmer_history_does_not_restore_mapped_history(ml_client):
    selection = FieldSelection.model_validate(ml_client.get(f"/v1/fields/{F1['field_id']}").json())
    payload = ml_request(selection, AnalysisOptions(crop_history=[]))
    assert "crop_history" not in payload["field"]
    for crop in ["corn", "soybean", "winter_wheat", "cereal_rye"]:
        payload = ml_request(selection, AnalysisOptions(crop_history=[CropYear(year=2025, crop=crop)]))
        assert payload["field"]["crop_history"][0]["crop"] == crop
