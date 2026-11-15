"""Profitability estimate: the pure calculation (no DB) plus the HTTP route."""

import pytest

from app.models import ProfitEstimateRequest
from app.profitability import baseline, estimate_profit


def req(**kw) -> ProfitEstimateRequest:
    return ProfitEstimateRequest.model_validate({"crop": "Corn", "state": "IA", **kw})


def test_model_yield_with_rent_override_and_published_rotation_costs():
    est = estimate_profit(req(
        predicted_yield=205, previous_crop="Soybeans", cost_overrides={"land_rent_per_acre": 250},
    ))
    assert est.yield_source == "model" and est.yield_per_acre == 205
    by_key = {c.key: c for c in est.costs}
    assert by_key["fertilizer"].amount_per_acre == 169.44
    assert by_key["fertilizer"].source == "baseline_rotation"
    assert not any(c.source == "baseline_with_nitrogen_credit" for c in est.costs)
    assert "Corn Following Soybeans" in est.cost_profile
    assert by_key["land_rent"].amount_per_acre == 250 and by_key["land_rent"].source == "farmer"

    total = sum(c.amount_per_acre for c in est.costs)
    low, base, high = baseline.PRICES[("Corn", "IA")]
    assert est.scenarios.base.revenue_per_acre == round(205 * base, 2)
    assert est.scenarios.base.profit_per_acre == round(205 * base - total, 2)
    s = est.scenarios
    assert s.low.profit_per_acre < s.base.profit_per_acre < s.high.profit_per_acre
    assert f"Revenue = 205 bu × ${base:.2f} = ${205 * base:,.2f} (base price)." in est.assumptions
    # Model yield, sourced IA corn price and costs, farmer's rent: nothing from a placeholder.
    assert est.baseline.is_placeholder is False


def test_fallback_yield_and_baseline_costs():
    est = estimate_profit(req(crop="Soybeans", state="NE"))
    assert est.yield_source == "budget_reference"
    assert est.yield_per_acre == 50
    assert all(c.source == "baseline" for c in est.costs)
    expected = sum(baseline.COSTS[("Soybeans", "NE")].values()) + baseline.LAND_RENT["NE"]
    assert est.scenarios.base.cost_per_acre == expected
    assert est.baseline.is_placeholder is (("land_rent", "NE") in baseline.PLACEHOLDERS)


def test_published_soybeans_after_soybeans_profile_is_used_without_extra_nitrogen_credit():
    fert = baseline.COSTS[("Corn", "IL")]["fertilizer"]
    corn_on_corn = estimate_profit(req(state="IL", previous_crop="Corn"))
    assert next(c for c in corn_on_corn.costs if c.key == "fertilizer").amount_per_acre == fert
    soy_after_soy = estimate_profit(req(crop="Soybeans", state="IL", previous_crop="Soybeans"))
    assert soy_after_soy.yield_per_acre == 74
    assert soy_after_soy.scenarios.base.cost_per_acre == 516 + baseline.LAND_RENT["IL"]
    assert all(c.source != "baseline_with_nitrogen_credit" for c in soy_after_soy.costs)


def test_iowa_rotation_uses_published_cost_and_yield_pair_without_a_second_credit():
    est = estimate_profit(req(previous_crop="soybean", cost_overrides={"land_rent_per_acre": 274}))
    # ISU 2026 A1-20 p. 3, middle column: 211 bu and $911.98 total including $274 land.
    assert est.yield_per_acre == 211
    assert est.scenarios.base.cost_per_acre == 911.98
    assert est.yield_source == "budget_reference"


def test_illinois_reference_reproduces_extension_crop_only_returns(monkeypatch):
    # farmdoc May 2026 Table 2. Its reported farmer returns also include $25 ARC/PLC;
    # our crop-only calculation excludes that payment and must not fake it as crop revenue.
    monkeypatch.setitem(baseline.PRICES, ("Corn", "IL"), (4, 4.50, 5))
    monkeypatch.setitem(baseline.PRICES, ("Soybeans", "IL"), (10, 11.50, 13))
    corn = estimate_profit(req(state="IL", previous_crop="Soybeans",
                               cost_overrides={"land_rent_per_acre": 321}))
    soy = estimate_profit(req(crop="Soybeans", state="IL", previous_crop="Corn",
                              cost_overrides={"land_rent_per_acre": 321}))
    assert corn.yield_per_acre == 241 and corn.scenarios.base.cost_per_acre == 1154
    assert corn.scenarios.base.profit_per_acre == -69.50  # A real loss must remain negative.
    assert soy.yield_per_acre == 76 and soy.scenarios.base.cost_per_acre == 832
    assert soy.scenarios.base.profit_per_acre == 42


def test_farmer_total_preserves_independent_state_yield_fallback():
    est = estimate_profit(req(state="IL", cost_overrides={"total_cost_per_acre": 700}))
    assert est.yield_per_acre == baseline.DEFAULT_YIELD[("Corn", "IL")]
    assert est.yield_source == "baseline_default" and est.cost_profile is None


def test_total_cost_override_replaces_everything():
    est = estimate_profit(req(
        previous_crop="Soybeans", cost_overrides={"total_cost_per_acre": 700, "land_rent_per_acre": 1},
    ))
    assert [(c.key, c.amount_per_acre, c.source) for c in est.costs] == [("total", 700, "farmer")]
    assert est.scenarios.high.cost_per_acre == 700


def test_placeholder_flag_follows_the_inputs_used():
    iowa_wheat = estimate_profit(req(crop="Winter Wheat", cost_overrides={"total_cost_per_acre": 300}))
    assert iowa_wheat.baseline.is_placeholder is True
    assert any("Placeholder values" in a for a in iowa_wheat.assumptions)
    il_wheat = estimate_profit(req(
        crop="Winter Wheat", state="IL", cost_overrides={"total_cost_per_acre": 300},
    ))
    assert il_wheat.baseline.is_placeholder is False


def test_every_baseline_number_has_a_source_or_is_marked_placeholder():
    data = baseline.DATA
    entries = [(f"{t}/{c}/{s}", e) for t in ("prices", "default_yield", "costs")
               for c, by_state in data[t].items() for s, e in by_state.items()]
    entries += [(f"land_rent/{s}", e) for s, e in data["land_rent"].items()]
    entries += [("nitrogen_credit", data["nitrogen_credit"]), ("nitrogen_price", data["nitrogen_price"])]
    assert len(entries) == 3 * 9 + 3 + 2
    for name, e in entries:
        assert e.get("unit"), name
        if e.get("placeholder"):
            assert e.get("placeholder_reason"), f"{name}: placeholder without a reason"
            continue
        src = e.get("source") or {}
        for field in ("publisher", "document", "url", "year", "retrieved"):
            assert src.get(field), f"{name}: source is missing {field!r}"
        assert e.get("data_years") or name.startswith("nitrogen_credit"), f"{name}: no data year"
    for c, by_state in data["prices"].items():
        for s, e in by_state.items():
            assert e["low"] < e["base"] < e["high"], (c, s)


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
