"""Budgets must conserve dollars, count time/area correctly, and expose missing inputs."""

import math

import pytest

from app.models import ProfitEstimateRequest, RotationBudgetOptions
from app.profitability import estimate_profit
from app.profitability.rotation import COVER, compare_budgets, estimate_rotation_budget


def season(year, crop, cover=False):
    return {"year": year, "crop": crop, "season": "cover" if cover else "main"}


def budget(sequence, state="IL", area=40, previous=None, **options):
    return estimate_rotation_budget(sequence, state, area, RotationBudgetOptions(**options), previous)


def crop_override(crop, cost=300):
    return {"crop": crop, "production_cost_per_acre": cost,
            "revenue_per_acre": {"low": 400, "base": 600, "high": 900}}


def test_rotation_reuses_crop_calculator_and_counts_land_once_per_year():
    seq = [season(1, "corn"), season(1, "cereal_rye", True), season(2, "soybean"),
           season(2, "cereal_rye", True), season(3, "corn")]
    result = budget(seq, previous="Soybeans", land_rent_per_acre=200, cover_cost_per_acre=40)
    assert result.status == "estimated" and not result.uses_placeholders
    assert result.is_illustrative and result.horizon_years == 3
    expected = []
    for year, crop, previous, cover in [(1, "Corn", "Soybeans", 40), (2, "Soybeans", "Corn", 40),
                                        (3, "Corn", "Soybeans", 0)]:
        estimate = estimate_profit(ProfitEstimateRequest(
            crop=crop, state="IL", previous_crop=previous, cost_overrides={"land_rent_per_acre": 200},
        ))
        actual = result.years[year - 1]
        assert actual.land_rent_per_acre == 200
        assert actual.cover_cost_per_acre == cover
        assert actual.scenarios.base.revenue_per_acre == estimate.scenarios.base.revenue_per_acre
        assert actual.scenarios.base.cost_per_acre == estimate.scenarios.base.cost_per_acre + cover
        expected.append(actual.scenarios.base)
    total = result.horizon_total.base
    assert total.revenue_per_acre == round(sum(x.revenue_per_acre for x in expected), 2)
    assert total.cost_per_acre == round(sum(x.cost_per_acre for x in expected), 2)
    assert total.profit_per_acre == round(total.revenue_per_acre - total.cost_per_acre, 2)
    assert total.field_profit == round(total.field_revenue - total.field_cost, 2)
    assert total.field_revenue == round(sum(x.field_revenue for x in expected), 2)
    assert total.field_cost == round(sum(x.field_cost for x in expected), 2)
    annual = result.annual_average.base
    assert annual.cost_per_acre == round(total.cost_per_acre / 3, 2)
    assert annual.profit_per_acre == round(annual.revenue_per_acre - annual.cost_per_acre, 2)
    assert result.annual_average.low.profit_per_acre < annual.profit_per_acre
    assert result.annual_average.high.profit_per_acre > annual.profit_per_acre


def test_first_year_predecessor_is_actual_history_not_the_end_of_the_plan():
    seq = [season(1, "corn"), season(2, "soybean")]
    corn = budget(seq, previous="Corn", land_rent_per_acre=0)
    soy = budget(seq, previous="soybean", land_rent_per_acre=0)
    unknown = budget(seq, land_rent_per_acre=0)
    assert corn.years[0].nitrogen_credit_per_acre == unknown.years[0].nitrogen_credit_per_acre == 0
    assert soy.years[0].nitrogen_credit_per_acre == 0  # Published profile already includes rotation effects.
    assert soy.years[0].production_cost_per_acre == 833
    assert corn.years[0].production_cost_per_acre == 848
    assert soy.years[0].yield_per_acre == 241 and corn.years[0].yield_per_acre == 231


def test_cover_is_cost_only_and_comparison_uses_matching_scenarios():
    current = budget([season(1, "corn")], land_rent_per_acre=0)
    alternative = budget([season(1, "corn"), season(1, "cereal_rye", True)],
                         land_rent_per_acre=0, cover_cost_per_acre=50)
    compare_budgets([current, alternative], current)
    assert current.delta_vs_current_per_acre.base == 0
    for key in ("low", "base", "high"):
        assert getattr(alternative.delta_vs_current_per_acre, key) == -50
        assert (getattr(alternative.annual_average, key).revenue_per_acre
                == getattr(current.annual_average, key).revenue_per_acre)


def test_unsupported_crop_leaves_whole_rotation_totals_unavailable():
    result = budget([season(1, "corn"), season(2, "barley")], land_rent_per_acre=0)
    assert result.status == "partial" and result.years[0].scenarios
    assert result.years[1].scenarios is None
    assert result.horizon_total is None and result.annual_average is None
    assert any("barley" in x for x in result.missing_inputs)
    compare_budgets([result], result)
    assert result.delta_vs_current_per_acre is None


def test_farmer_budget_supports_other_crops_and_states_without_reusing_wrong_state_data():
    result = budget([season(1, "sorghum")], state="KS", land_rent_per_acre=100,
                    crop_overrides=[crop_override("sorghum")])
    assert result.status == "estimated" and not result.uses_placeholders
    assert result.annual_average.base.revenue_per_acre == 600
    assert result.annual_average.base.cost_per_acre == 400
    assert result.annual_average.base.profit_per_acre == 200
    assert not result.sources
    assert result.years[0].yield_per_acre is None


def test_farmer_production_total_gets_no_extra_nitrogen_discount():
    result = budget([season(1, "corn")], previous="Soybeans", land_rent_per_acre=123,
                    crop_overrides=[crop_override("corn", 700)])
    assert result.annual_average.base.cost_per_acre == 823
    assert result.years[0].nitrogen_credit_per_acre == 0


def test_double_crop_budgets_are_not_summed_as_two_full_yield_single_crops():
    result = budget([season(1, "winter_wheat"), season(1, "soybean")], land_rent_per_acre=100)
    assert result.status == "unavailable" and result.horizon_total is None
    assert any("double-crop" in x for x in result.missing_inputs)
    supplied = budget([season(1, "winter_wheat"), season(1, "soybean")], land_rent_per_acre=100,
                      crop_overrides=[crop_override("winter_wheat+soybean", 300)])
    assert supplied.status == "estimated"
    assert supplied.horizon_total.base.cost_per_acre == 400
    assert supplied.horizon_total.base.revenue_per_acre == 600


def test_gaps_in_sequence_are_not_skipped_and_fallow_is_not_free():
    result = budget([season(1, "corn"), season(3, "fallow")], land_rent_per_acre=100)
    assert result.status == "partial" and len(result.years) == 3
    assert result.years[1].scenarios is None and result.years[2].scenarios is None
    assert len(result.missing_inputs) == 2


def test_rent_and_unknown_cover_costs_must_be_supplied():
    result = budget([season(1, "sorghum")], state="KS", crop_overrides=[crop_override("sorghum")])
    assert result.status == "unavailable"
    assert any("land cost" in x for x in result.missing_inputs)
    seq = [season(1, "corn"), season(1, "hairy_vetch", True)]
    missing = budget(seq, land_rent_per_acre=0)
    supplied = budget(seq, land_rent_per_acre=0, cover_cost_per_acre=0)
    assert missing.annual_average is None and missing.years[0].cover_cost_per_acre is None
    assert supplied.status == "estimated"  # Explicit zero is a valid farmer assumption.


def test_cover_cost_requires_local_input_and_unsourced_wheat_has_no_totals():
    seq = [season(1, "corn"), season(1, "cereal_rye", True)]
    illinois = budget(seq, state="IL", land_rent_per_acre=0)
    iowa = budget(seq, state="IA", land_rent_per_acre=0)
    rent = budget([season(1, "corn")], state="IL")
    wheat = budget([season(1, "winter_wheat")], state="IA", land_rent_per_acre=0)
    assert illinois.status == iowa.status == "unavailable"
    assert illinois.annual_average is None and iowa.annual_average is None
    assert not illinois.uses_placeholders and not iowa.uses_placeholders
    assert not rent.uses_placeholders and rent.status == "estimated"
    assert wheat.uses_placeholders and wheat.status == "unavailable"
    assert wheat.annual_average is None and wheat.years[0].production_cost_per_acre is None
    assert illinois.years[0].cover_cost_per_acre is None
    assert not any(s.url == COVER["source"]["url"] for s in illinois.sources)
    assert any("planting and termination" in s for s in iowa.missing_inputs)


def test_before_land_return_and_break_even_reconcile_with_net_return():
    result = budget([season(1, "corn")], previous="Soybeans", land_rent_per_acre=321)
    year = result.years[0]
    s = year.scenarios.base
    assert s.return_before_land_per_acre == round(s.profit_per_acre + 321, 2)
    assert year.break_even_price_per_unit == round(s.cost_per_acre / 241, 2)
    assert result.annual_average.base.return_before_land_per_acre == s.return_before_land_per_acre
    assert result.horizon_total.base.return_before_land_per_acre == s.return_before_land_per_acre


def test_missing_area_preserves_per_acre_numbers_but_not_field_totals():
    result = budget([season(1, "corn")], area=None)
    assert result.status == "estimated" and result.area_acres is None
    assert result.horizon_total.base.field_profit is None
    assert math.isfinite(result.horizon_total.base.profit_per_acre)


@pytest.mark.parametrize("data", [
    {"land_rent_per_acre": -1}, {"land_rent_per_acre": float("inf")},
    {"cover_cost_per_acre": -1}, {"cover_cost_per_acre": float("nan")},
    {"crop_overrides": [crop_override("corn"), crop_override("corn")]},
    {"crop_overrides": [crop_override("Corn")]},
    {"crop_overrides": [{**crop_override("corn"), "production_cost_per_acre": -1}]},
    {"crop_overrides": [{**crop_override("corn"),
                         "revenue_per_acre": {"low": 600, "base": 400, "high": 900}}]},
])
def test_invalid_budget_assumptions_are_rejected(data):
    with pytest.raises(ValueError):
        RotationBudgetOptions(**data)
