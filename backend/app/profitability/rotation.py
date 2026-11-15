"""Illustrative enterprise budgets for the ML crop sequence, independent of ML's income index.

No fit/confidence/income score is converted to yield or money. Land is charged per year, not
per season. An incomplete year never contributes a pretend zero to a whole-rotation total.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, TypedDict

from app.models import (
    BudgetAmounts,
    BudgetScenario,
    BudgetScenarios,
    BudgetYear,
    CostOverrides,
    ProfitCrop,
    ProfitEstimateRequest,
    ProfitState,
    RotationBudget,
    RotationBudgetOptions,
    RotationBudgetRequest,
)
from app.profitability import baseline
from app.profitability.calc import estimate_profit
from app.profitability.money import ACRES_PER_HECTARE, add, break_even, divide, field_amounts, money

SCENARIOS = ("low", "base", "high")
CASH_CROPS = {
    "corn": ProfitCrop.corn, "soybean": ProfitCrop.soybeans, "winter_wheat": ProfitCrop.winter_wheat,
}
COVER = json.loads(Path(__file__).with_name("cover_reference.json").read_text())


class BudgetSeason(TypedDict):
    year: int
    season: Literal["main", "cover"]
    crop: str


def _scenarios(
    revenues: Sequence[float], cost: float, acres: float | None, land_cost: float,
) -> BudgetScenarios:
    cost = money(cost)
    values = {}
    for key, revenue in zip(SCENARIOS, revenues, strict=True):
        revenue = money(revenue)
        profit = add(revenue, -cost)
        values[key] = BudgetScenario(
            revenue_per_acre=revenue, cost_per_acre=cost, profit_per_acre=profit,
            **field_amounts(revenue, cost, acres),
            return_before_land_per_acre=add(profit, land_cost),
        )
    return BudgetScenarios(**values)


def estimate_rotation_budget(
    sequence: Sequence[BudgetSeason], state: str, area_ha: float | None,
    options: RotationBudgetOptions, previous_crop: str | None = None, horizon_years: int | None = None,
) -> RotationBudget:
    # Apply the same bounded plan validation to standalone requests, ML and comparisons.
    validated = RotationBudgetRequest(
        sequence=sequence, state=state, area_ha=area_ha, options=options,
        previous_crop=previous_crop, horizon_years=horizon_years,
    )
    sequence = [s.model_dump() for s in validated.sequence]
    horizon = validated.horizon_years or max(s["year"] for s in sequence)
    acres = area_ha * ACRES_PER_HECTARE if area_ha is not None and area_ha > 0 else None
    notes = [
        "Illustrative USD budget, not a profit forecast. ML chooses the crop sequence; its income index "
        "does not predict yield or dollar returns.",
        "Low/base/high are historical price sensitivity, not bad/normal/good-year forecasts. "
        "Reference yields are matched to the selected extension production-cost budget. "
        "Farmer crop overrides instead use the supplied gross revenue scenarios.",
        "All crops use matching low/base/high scenarios; these are not probability intervals.",
        "Land is charged once per year. Cover crops are terminated, with no harvested revenue. "
        "No cost-share, carbon payments, grazing income or future soil-health savings are assumed.",
        "No weather/field suitability yield adjustment, inflation or discounting is applied. "
        "Field totals use the estimated mapped area, which may differ from farmed acres.",
        "Return after costs includes the published labor, machinery ownership/depreciation and overhead "
        "allowances. It is not cash flow. Return before land shows what remains to cover the land charge.",
        "Farmer production overrides define their own cost basis. Monetary amounts use decimal "
        "half-up rounding to cents; field profit equals field revenue minus field cost.",
    ]
    missing, years, sources = [], [], []
    placeholders = False

    def used(entry: dict) -> bool:
        nonlocal placeholders
        placeholders |= bool(entry.get("placeholder"))
        source = baseline.source_ref(entry)
        if source and source not in sources:
            sources.append(source)
        return not entry.get("placeholder")

    rent = options.land_rent_per_acre
    if rent is None and state in baseline.DATA["land_rent"]:
        entry = baseline.DATA["land_rent"][state]
        if used(entry):
            rent = money(entry["value"])
            notes.append(f"Land cost uses the {entry['data_years']} {state} state reference, "
                         "not a county or local lease quote.")
    elif rent is not None:
        rent = money(rent)
        notes.append("Annual land cost is the farmer's figure; zero means no land charge.")
    if rent is None:
        missing.append(f"No sourced land-rent baseline for {state}; enter an annual land cost.")
    rent_sources = list(sources)
    overrides = {c.crop: c for c in options.crop_overrides}
    previous = (previous_crop or "").strip().lower().replace("_", " ")

    for year in range(1, horizon + 1):
        items = [s for s in sequence if s["year"] == year]
        main = [s["crop"] for s in items if s["season"] == "main"]
        covers = [s["crop"] for s in items if s["season"] == "cover"]
        production = revenues = yld = unit = profile = None
        yield_source = "unavailable"
        year_sources = list(rent_sources)
        credit = 0.0
        crop_key = "+".join(main)
        if crop_key in overrides:
            override = overrides[crop_key]
            production = money(override.production_cost_per_acre)
            revenues = [getattr(override.revenue_per_acre, k) for k in SCENARIOS]
            yield_source = "farmer"
            note = (f"{crop_key} uses farmer gross revenues and non-land production cost; "
                    "no extra nitrogen credit.")
            if note not in notes:
                notes.append(note)
        elif len(main) != 1:
            missing.append(f"Year {year}: needs a specific double-crop budget." if len(main) > 1
                           else f"Year {year}: no main crop to budget.")
        elif main[0] in CASH_CROPS and state in ProfitState:
            crop = CASH_CROPS[main[0]]
            # Rent is handled once below, so ask the existing calculator for non-land costs only.
            estimate = estimate_profit(ProfitEstimateRequest(
                crop=crop, state=ProfitState(state),
                previous_crop="Soybeans" if previous in {"soybeans", "soybean"} else previous,
                cost_overrides=CostOverrides(land_rent_per_acre=0),
            ))
            if estimate.scenarios is not None:
                production = estimate.scenarios.base.cost_per_acre
                revenues = [getattr(estimate.scenarios, k).revenue_per_acre for k in SCENARIOS]
            else:
                missing.extend(f"Year {year}: {item}" for item in estimate.missing_inputs)
            yld, unit = estimate.yield_per_acre, estimate.yield_unit
            yield_source = estimate.yield_source
            placeholders |= estimate.baseline.is_placeholder
            year_sources.extend(s for s in estimate.sources if s not in year_sources)
            profile = estimate.cost_profile
            cost_entry = baseline.cost_entry(crop, ProfitState(state), previous)
            tables = ["prices", "costs"]
            if estimate.yield_source == "baseline_default":
                tables.append("default_yield")
            for table in tables:
                entry = cost_entry if table == "costs" else baseline.DATA[table][crop.value][state]
                used(entry)
                if entry.get("placeholder"):
                    note = f"{crop.value} / {state}: {table} uses a placeholder, not sourced local data."
                    if note not in notes:
                        notes.append(note)
            if any(c.source == "baseline_with_nitrogen_credit" for c in estimate.costs):
                normal = sum(baseline.COSTS[(crop, ProfitState(state))].values())
                credit = add(normal, -production)
                used(baseline.DATA["nitrogen_credit"])
                used(baseline.DATA["nitrogen_price"])
                notes.append(f"Year {year}: corn after soybeans reduces fertilizer cost "
                             f"by ${credit:.2f}/acre.")
        else:
            crop = main[0]
            missing.append(f"Year {year}: no {crop.replace('_', ' ')} budget for {state}; "
                           "provide local gross revenue and production costs.")

        cover_cost = 0.0
        for cover in covers:
            if options.cover_cost_per_acre is not None:
                cover_cost = add(cover_cost, money(options.cover_cost_per_acre))
            else:
                missing.append(f"Year {year}: enter planting and termination costs "
                               f"for {cover.replace('_', ' ')}.")
        if covers and options.cover_cost_per_acre is None:
            cover_cost = None
        scenarios = None
        if revenues is not None and rent is not None and cover_cost is not None:
            scenarios = _scenarios(revenues, add(production, rent, cover_cost), acres, rent)
        years.append(BudgetYear(
            year=year, main_crops=main, cover_crops=covers, production_cost_per_acre=production,
            land_rent_per_acre=rent,
            cover_cost_per_acre=cover_cost,
            nitrogen_credit_per_acre=credit, yield_per_acre=yld, yield_unit=unit, scenarios=scenarios,
            cost_profile=profile,
            break_even_price_per_unit=(break_even(scenarios.base.cost_per_acre, yld)
                                       if scenarios is not None and yld else None),
            yield_source=yield_source, sources=year_sources,
        ))
        # A winter cover is not a harvested predecessor and earns no extra nitrogen credit.
        previous = main[-1] if main else ""

    complete = all(y.scenarios is not None for y in years)
    total = average = None
    if complete:
        revenues = [add(*(getattr(y.scenarios, k).revenue_per_acre for y in years)) for k in SCENARIOS]
        cost = add(*(y.scenarios.base.cost_per_acre for y in years))
        land = add(*(y.land_rent_per_acre for y in years))
        total = _scenarios(revenues, cost, acres, land)
        average = _scenarios([divide(v, horizon) for v in revenues], divide(cost, horizon),
                             acres, divide(land, horizon))
        if acres is not None:
            # Field totals sum the yearly cents, rather than rescaling a rounded per-acre average.
            for key in SCENARIOS:
                field_revenue = add(*(getattr(y.scenarios, key).field_revenue for y in years))
                field_cost = add(*(getattr(y.scenarios, key).field_cost for y in years))
                whole, annual = getattr(total, key), getattr(average, key)
                whole.field_revenue, whole.field_cost = field_revenue, field_cost
                whole.field_profit = add(field_revenue, -field_cost)
                annual.field_revenue = divide(field_revenue, horizon)
                annual.field_cost = divide(field_cost, horizon)
                annual.field_profit = add(annual.field_revenue, -annual.field_cost)
    return RotationBudget(
        status="estimated" if complete else "partial" if any(y.scenarios for y in years) else "unavailable",
        horizon_years=horizon, area_acres=acres,
        years=years, annual_average=average, horizon_total=total, uses_placeholders=placeholders,
        baseline_version=baseline.BASELINE_VERSION + "+rotation-" + COVER["version"],
        assumptions=notes, missing_inputs=missing, sources=sources,
    )


def compare_budgets(budgets: Sequence[RotationBudget], current: RotationBudget) -> None:
    """Paired price scenarios, not a confidence interval or a change to ML's ranking."""
    for budget in budgets:
        budget.delta_vs_current_per_acre = None
        if (budget.annual_average is not None and current.annual_average is not None
                and budget.horizon_years == current.horizon_years):
            budget.delta_vs_current_per_acre = BudgetAmounts(**{
                k: add(getattr(budget.annual_average, k).profit_per_acre,
                       -getattr(current.annual_average, k).profit_per_acre)
                for k in SCENARIOS
            })
