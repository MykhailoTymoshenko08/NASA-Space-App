"""Profitability estimate: the pure calculation (no DB) plus the HTTP route."""

import pytest

from app.models import ProfitEstimateRequest
from app.profitability import baseline, estimate_profit


def req(**kw) -> ProfitEstimateRequest:
    return ProfitEstimateRequest.model_validate({"crop": "Corn", "state": "IA", **kw})


def test_model_yield_with_rent_override_and_nitrogen_credit():
    est = estimate_profit(req(
        predicted_yield=205, previous_crop="Soybeans", cost_overrides={"land_rent_per_acre": 250},
    ))
    assert est.yield_source == "model" and est.yield_per_acre == 205
    by_key = {c.key: c for c in est.costs}
    credit = baseline.NITROGEN_CREDIT_LB_PER_ACRE * baseline.NITROGEN_PRICE_PER_LB
    assert by_key["fertilizer"].amount_per_acre == baseline.COSTS[("Corn", "IA")]["fertilizer"] - credit
    assert by_key["fertilizer"].source == "baseline_with_nitrogen_credit"
    assert by_key["land_rent"].amount_per_acre == 250 and by_key["land_rent"].source == "farmer"

    total = sum(c.amount_per_acre for c in est.costs)
    low, base, high = baseline.PRICES["Corn"]
    assert est.scenarios.base.revenue_per_acre == round(205 * base, 2)
    assert est.scenarios.base.profit_per_acre == round(205 * base - total, 2)
    s = est.scenarios
    assert s.low.profit_per_acre < s.base.profit_per_acre < s.high.profit_per_acre
    assert f"Revenue = 205 bu × ${base:.2f} = ${205 * base:,.2f} (base price)." in est.assumptions


def test_fallback_yield_and_baseline_costs():
    est = estimate_profit(req(crop="Soybeans", state="NE"))
    assert est.yield_source == "baseline_default"
    assert est.yield_per_acre == baseline.DEFAULT_YIELD[("Soybeans", "NE")]
    assert all(c.source == "baseline" for c in est.costs)
    expected = sum(baseline.COSTS[("Soybeans", "NE")].values()) + baseline.LAND_RENT["NE"]
    assert est.scenarios.base.cost_per_acre == expected
    assert est.baseline.is_placeholder is baseline.IS_PLACEHOLDER


def test_no_nitrogen_credit_for_corn_after_corn_or_for_soybeans():
    fert = baseline.COSTS[("Corn", "IL")]["fertilizer"]
    corn_on_corn = estimate_profit(req(state="IL", previous_crop="Corn"))
    assert next(c for c in corn_on_corn.costs if c.key == "fertilizer").amount_per_acre == fert
    soy_after_soy = estimate_profit(req(crop="Soybeans", previous_crop="Soybeans"))
    assert all(c.source == "baseline" for c in soy_after_soy.costs)


def test_total_cost_override_replaces_everything():
    est = estimate_profit(req(
        previous_crop="Soybeans", cost_overrides={"total_cost_per_acre": 700, "land_rent_per_acre": 1},
    ))
    assert [(c.key, c.amount_per_acre, c.source) for c in est.costs] == [("total", 700, "farmer")]
    assert est.scenarios.high.cost_per_acre == 700


def test_unsupported_input_rejected():
    for bad in ({"state": "TX"}, {"crop": "Rice"}, {"predicted_yield": 0}, {"cost_overrides": {"seed": 1}}):
        with pytest.raises(ValueError):
            req(**bad)


@pytest.mark.contract
def test_route_matches_contract(client):
    from tests.contract import assert_matches_contract

    body = {"crop": "Corn", "state": "IA", "predicted_yield": 205}
    r = client.post("/v1/profitability/estimate", json=body)
    assert r.status_code == 200
    assert_matches_contract(r)
    r = client.post("/v1/profitability/estimate", json={"crop": "Corn", "state": "TX"})
    assert r.status_code == 422
    assert_matches_contract(r)
