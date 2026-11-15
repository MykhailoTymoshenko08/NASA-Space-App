"""Financial inputs, rounding, missing data and protected standalone API paths."""

import copy
import json
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.auth.tokens import create_access_token
from app.models import ProfitEstimateRequest, RotationBudgetOptions, RotationBudgetRequest
from app.profitability import baseline, estimate_profit
from app.profitability.money import ACRES_PER_HECTARE, add, money, multiply
from app.profitability.rotation import compare_budgets, estimate_rotation_budget
from scripts.build_profit_baseline import build_land_rent
from tests.contract import assert_matches_contract

PLAN = [{"year": 1, "season": "main", "crop": "corn"}]
ENDPOINTS = [
    ("POST", "/v1/profitability/estimate", {"crop": "Corn", "state": "IA"}),
    ("POST", "/v1/profitability/rotation", {"sequence": PLAN, "state": "IA"}),
    ("GET", "/v1/profitability/baselines", None),
]


@pytest.fixture
def signed_in(client):
    response = client.post("/v1/auth/register", json={
        "email": f"finance-{uuid.uuid4().hex}@example.com", "password": "correct horse 9",
    })
    assert response.status_code == 201, response.text
    body = response.json()
    return client, {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


def estimate(**values):
    return estimate_profit(ProfitEstimateRequest(crop="Corn", state="IA", **values))


@pytest.mark.contract
@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_all_financial_routes_require_sign_in(client, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert_matches_contract(response)


@pytest.mark.contract
@pytest.mark.parametrize("token_kind", ["malformed", "expired", "wrong_signature", "revoked"])
def test_financial_routes_reject_invalid_sessions(signed_in, token_kind):
    client, _, user = signed_in
    svc = client.app.state.services
    secret = "wrong-secret-" + "x" * 32 if token_kind == "wrong_signature" else svc.jwt_secret
    token = create_access_token(
        uuid.UUID(user["id"]), secret,
        timedelta(minutes=-1 if token_kind == "expired" else 15),
        999 if token_kind == "revoked" else 0,
    )
    if token_kind == "malformed":
        token = "not-a-jwt"
    for method, path, body in ENDPOINTS:
        response = client.request(method, path, json=body, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert_matches_contract(response)


@pytest.mark.contract
def test_baselines_expose_all_coverage_and_sources(signed_in):
    client, headers, _ = signed_in
    response = client.get("/v1/profitability/baselines", headers=headers)
    assert response.status_code == 200
    assert_matches_contract(response)
    entries = response.json()
    assert len(entries) == 9
    for entry in entries:
        if (entry["crop"], entry["state"]) == ("Winter Wheat", "IA"):
            assert entry["status"] == "unavailable" and entry["scenarios"] is None
            assert len(entry["missing_inputs"]) == 3
        else:
            assert entry["status"] == "estimated" and entry["sources"]
            assert not entry["baseline"]["is_placeholder"] and not entry["missing_inputs"]
        assert all(s["url"] and s["coverage_period"] for s in entry["sources"])


@pytest.mark.contract
def test_standalone_rotation_matches_analysis_calculator(signed_in):
    client, headers, _ = signed_in
    body = {"state": "IA", "sequence": PLAN, "area_ha": 40,
            "previous_crop": "Soybeans", "options": {"land_rent_per_acre": 274}}
    response = client.post("/v1/profitability/rotation", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert_matches_contract(response)
    expected = estimate_rotation_budget(PLAN, "IA", 40, RotationBudgetOptions(land_rent_per_acre=274),
                                        "Soybeans")
    assert response.json() == expected.model_dump(mode="json")
    assert response.json()["years"][0]["yield_per_acre"] == 211
    assert response.json()["years"][0]["scenarios"]["base"]["cost_per_acre"] == 911.98


@pytest.mark.contract
def test_missing_rotation_inputs_are_contract_results(signed_in):
    client, headers, _ = signed_in
    response = client.post("/v1/profitability/rotation", headers=headers, json={
        "sequence": [{"year": 1, "season": "main", "crop": "sorghum"}], "state": "KS",
    })
    assert response.status_code == 200
    assert_matches_contract(response)
    assert response.json()["status"] == "unavailable"
    assert response.json()["horizon_total"] is None
    assert len(response.json()["missing_inputs"]) == 2


@pytest.mark.contract
def test_farmer_wheat_and_crop_failure_complete_through_http(signed_in):
    client, headers, _ = signed_in
    for yield_value in (0, 60):
        response = client.post("/v1/profitability/estimate", headers=headers, json={
            "crop": "Winter Wheat", "state": "IA", "yield_per_acre": yield_value,
            "price_overrides": {"low": 0, "base": 5, "high": 6},
            "cost_overrides": {"total_cost_per_acre": 250}, "area_ha": 0.1,
        })
        assert response.status_code == 200, response.text
        assert_matches_contract(response)
        result = response.json()
        assert result["status"] == "estimated" and not result["missing_inputs"]
        assert result["yield_source"] == result["price_source"] == "farmer"
        assert result["scenarios"]["base"]["profit_per_acre"] == yield_value * 5 - 250
        assert result["scenarios"]["low"]["break_even_yield_per_acre"] is None


@pytest.mark.contract
@pytest.mark.parametrize("path,body", [
    ("estimate", {"crop": "Corn", "state": "IA", "predicted_yield": 1, "yield_per_acre": 1}),
    ("estimate", {"crop": "Corn", "state": "IA", "price_overrides": {"low": 5, "base": 4, "high": 6}}),
    ("estimate", {"crop": "Corn", "state": "IA", "cost_overrides": {"seed": "NaN"}}),
    ("rotation", {"state": "IA", "sequence": []}),
    ("rotation", {"state": "IA", "sequence": PLAN * 2}),
])
def test_financial_validation_errors_match_contract(signed_in, path, body):
    client, headers, _ = signed_in
    response = client.post("/v1/profitability/" + path, headers=headers, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert_matches_contract(response)


@pytest.mark.contract
def test_financial_routes_share_a_rate_limit(signed_in):
    client, headers, _ = signed_in
    client.app.state.limiters["profitability"].limit = 1
    assert client.post("/v1/profitability/estimate", headers=headers,
                       json={"crop": "Corn", "state": "IA"}).status_code == 200
    for method, path, body in ENDPOINTS:
        response = client.request(method, path, headers=headers, json=body)
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0
        assert_matches_contract(response)


def test_farmer_prices_yield_and_itemized_costs_replace_defaults():
    result = estimate(
        yield_per_acre=200, price_overrides={"low": 3, "base": 5, "high": 7}, area_ha=40,
        previous_crop="Soybeans", cost_overrides={"seed": 100, "fertilizer": 150,
        "chemicals": 50, "other_operating": 200, "land_rent_per_acre": 250},
    )
    assert result.status == "estimated" and not result.baseline.is_placeholder
    assert result.yield_source == result.price_source == "farmer"
    assert not result.sources and result.cost_profile is None
    assert all(line.source == "farmer" for line in result.costs)
    assert result.break_even_price_per_unit == 3.75
    scenario = result.scenarios.base
    assert scenario.revenue_per_acre == 1000 and scenario.cost_per_acre == 750
    assert scenario.profit_per_acre == 250 and scenario.return_before_land_per_acre == 500
    assert scenario.break_even_yield_per_acre == 150
    assert scenario.field_profit == add(scenario.field_revenue, -scenario.field_cost)
    assert scenario.field_revenue == multiply(1000, 40 * ACRES_PER_HECTARE)


def test_partial_cost_overrides_preserve_other_baseline_lines():
    result = estimate(previous_crop="Soybeans", cost_overrides={"fertilizer": 0, "land_rent_per_acre": 0})
    by_key = {line.key: line for line in result.costs}
    assert by_key["fertilizer"].amount_per_acre == 0 and by_key["fertilizer"].source == "farmer"
    assert by_key["seed"].amount_per_acre == 113.70 and by_key["seed"].source == "baseline_rotation"
    assert result.yield_per_acre == 211
    assert result.scenarios.base.cost_per_acre == 468.54
    assert result.scenarios.base.return_before_land_per_acre == result.scenarios.base.profit_per_acre


def test_unsourced_wheat_can_be_completed_with_farmer_inputs():
    unknown = estimate_profit(ProfitEstimateRequest(crop="Winter Wheat", state="IA"))
    assert unknown.yield_per_acre is None and unknown.scenarios is None
    assert all(line.key == "land_rent" for line in unknown.costs)
    result = estimate_profit(ProfitEstimateRequest(
        crop="Winter Wheat", state="IA", yield_per_acre=60,
        price_overrides={"low": 4, "base": 5, "high": 6}, cost_overrides={"total_cost_per_acre": 250},
    ))
    assert result.status == "estimated" and not result.baseline.is_placeholder
    assert result.scenarios.base.profit_per_acre == 50
    assert result.scenarios.base.return_before_land_per_acre is None
    assert not result.sources and not result.missing_inputs
    assert not any("Costs include the published" in note for note in result.assumptions)


@pytest.mark.parametrize("yield_value", [0, 0.001])
def test_zero_and_small_yields_preserve_losses_without_rounding_yield(yield_value):
    result = estimate(yield_per_acre=yield_value, price_overrides={"low": 0, "base": 5, "high": 6},
                      cost_overrides={"total_cost_per_acre": 100})
    assert result.yield_per_acre == yield_value
    assert result.scenarios.low.break_even_yield_per_acre is None
    assert result.scenarios.low.profit_per_acre == -100
    assert result.break_even_price_per_unit == (None if yield_value == 0 else 100000)
    assert result.scenarios.base.field_profit is None
    if yield_value:
        assert result.scenarios.base.revenue_per_acre == 0.01


def test_extreme_small_inputs_keep_json_finite():
    result = estimate(yield_per_acre=1e-320, price_overrides={"low": 1e-320, "base": 1, "high": 2},
                      cost_overrides={"total_cost_per_acre": 100})
    assert result.status == "estimated" and result.break_even_price_per_unit is None
    assert result.scenarios.low.break_even_yield_per_acre is None
    assert result.scenarios.low.profit_per_acre == -100
    json.dumps(result.model_dump(mode="json"), allow_nan=False)


def test_money_rounds_half_up_and_field_components_reconcile():
    assert money(1.005) == 1.01
    assert money(-1.005) == -1.01
    result = estimate(yield_per_acre=1, price_overrides={"low": 1.005, "base": 1.005, "high": 1.005},
                      cost_overrides={"total_cost_per_acre": 0.005}, area_ha=0.1)
    scenario = result.scenarios.base
    assert scenario.revenue_per_acre == 1.01 and scenario.cost_per_acre == 0.01
    assert scenario.profit_per_acre == 1
    for field in ("field_revenue", "field_cost", "field_profit"):
        assert Decimal(str(getattr(scenario, field))).as_tuple().exponent >= -2
    assert scenario.field_profit == add(scenario.field_revenue, -scenario.field_cost)


def test_rotation_field_totals_sum_yearly_cents_before_annual_averaging():
    result = estimate_rotation_budget(
        [{"year": year, "season": "main", "crop": "corn"} for year in range(1, 4)],
        "IA", 0.1, RotationBudgetOptions(land_rent_per_acre=0),
    )
    for key in ("low", "base", "high"):
        total, average = getattr(result.horizon_total, key), getattr(result.annual_average, key)
        yearly = [getattr(year.scenarios, key) for year in result.years]
        assert total.field_revenue == add(*(y.field_revenue for y in yearly))
        assert total.field_cost == add(*(y.field_cost for y in yearly))
        assert total.field_profit == add(*(y.field_profit for y in yearly))
        assert average.field_revenue == money(Decimal(str(total.field_revenue)) / 3)
        assert average.field_profit == add(average.field_revenue, -average.field_cost)


@pytest.mark.parametrize("values", [
    {"yield_per_acre": float("nan")}, {"predicted_yield": float("inf")},
    {"yield_per_acre": 10, "predicted_yield": 10}, {"area_ha": 0}, {"area_ha": float("inf")},
    {"price_overrides": {"low": 5, "base": 4, "high": 6}},
    {"price_overrides": {"low": 0, "base": float("nan"), "high": 6}},
    {"cost_overrides": {"seed": -1}},
    {"cost_overrides": {"total_cost_per_acre": 100, "seed": 1}},
])
def test_invalid_financial_inputs(values):
    with pytest.raises(ValueError):
        estimate(**values)


@pytest.mark.parametrize("sequence", [
    [], [{"year": 0, "season": "main", "crop": "corn"}],
    [{"year": 6, "season": "main", "crop": "corn"}], PLAN * 2,
    [{"year": 2, "season": "main", "crop": "corn"}, *PLAN],
    [{"year": 1, "season": "main", "crop": crop} for crop in ["corn", "soybean", "winter_wheat"]],
])
def test_invalid_rotation_plans(sequence):
    with pytest.raises(ValueError):
        RotationBudgetRequest(sequence=sequence, state="IA")


def test_declared_rotation_horizon_preserves_trailing_unknown_years():
    result = estimate_rotation_budget(PLAN, "IA", 1, RotationBudgetOptions(land_rent_per_acre=0),
                                      horizon_years=3)
    assert result.horizon_years == 3 and result.status == "partial"
    assert len(result.years) == 3 and result.years[0].scenarios is not None
    assert result.years[1].scenarios is result.years[2].scenarios is result.horizon_total is None
    assert len(result.missing_inputs) == 2
    with pytest.raises(ValueError):
        RotationBudgetRequest(sequence=[{"year": 2, "season": "main", "crop": "corn"}],
                              state="IA", horizon_years=1)


def test_rotation_withholds_placeholder_rent_and_clears_stale_deltas(monkeypatch):
    rent = {"value": 999, "placeholder": True, "placeholder_reason": "test unsourced rent"}
    monkeypatch.setitem(baseline.DATA["land_rent"], "IA", rent)
    result = estimate_rotation_budget(PLAN, "IA", 1, RotationBudgetOptions())
    assert result.status == "unavailable" and result.uses_placeholders
    assert result.years[0].land_rent_per_acre is None
    assert result.horizon_total is None and not any("999" in note for note in result.assumptions)
    supplied = estimate_rotation_budget(PLAN, "IA", 1, RotationBudgetOptions(land_rent_per_acre=0))
    assert supplied.status == "estimated" and not supplied.uses_placeholders
    compare_budgets([supplied], supplied)
    assert supplied.delta_vs_current_per_acre.base == 0
    compare_budgets([supplied], result)
    assert supplied.delta_vs_current_per_acre is None


def test_build_land_rent_without_api_key_keeps_verified_references(monkeypatch):
    monkeypatch.delenv("NASS_API_KEY", raising=False)
    result = build_land_rent("2099-01-01")
    assert {state: entry["value"] for state, entry in result.items()} == {"IA": 274, "IL": 261, "NE": 168}
    assert all(not e.get("placeholder") and e["source"]["retrieved"] == "2026-11-15"
               for e in result.values())


def test_estimates_do_not_mutate_baselines():
    before = copy.deepcopy(baseline.DATA)
    estimate(yield_per_acre=0, price_overrides={"low": 0, "base": 0, "high": 0})
    estimate_profit(ProfitEstimateRequest(crop="Winter Wheat", state="IA"))
    assert json.dumps(baseline.DATA, sort_keys=True) == json.dumps(before, sort_keys=True)
