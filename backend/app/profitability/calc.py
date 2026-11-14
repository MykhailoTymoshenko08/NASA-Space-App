"""Profit per acre = yield x price - costs, at a low / base / high price. Pure: no I/O, no globals mutated.

The tables come from `app.profitability.baseline`; tests may pass their own via `tables`.
"""

from types import ModuleType

from app.models import (
    ProfitBaselineInfo,
    ProfitCostItem,
    ProfitCrop,
    ProfitEstimate,
    ProfitEstimateRequest,
    ProfitScenario,
    ProfitScenarios,
)
from app.profitability import baseline as default_tables


def _money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def _num(x: float) -> str:
    return f"{x:g}"


def estimate_profit(req: ProfitEstimateRequest, tables: ModuleType = default_tables) -> ProfitEstimate:
    t = tables
    key = (req.crop, req.state)
    unit = t.YIELD_UNIT[req.crop]
    notes: list[str] = []

    # Yield
    if req.predicted_yield is not None:
        yld, yield_source = round(req.predicted_yield, 1), "model"
        notes.append(f"Yield = {_num(yld)} {unit}/acre, from the yield model.")
    else:
        yld, yield_source = float(t.DEFAULT_YIELD[key]), "baseline_default"
        notes.append(
            f"Yield = {_num(yld)} {unit}/acre, a typical {req.crop.value} yield for {req.state.value} "
            "(no model prediction given)."
        )

    # Costs
    overrides = req.cost_overrides
    costs: list[ProfitCostItem] = []
    if overrides.total_cost_per_acre is not None:
        costs.append(ProfitCostItem(
            key="total", label=t.COST_LABELS["total"],
            amount_per_acre=round(overrides.total_cost_per_acre, 2), source="farmer",
        ))
        notes.append(f"Costs = {_money(overrides.total_cost_per_acre)}/acre, the farmer's own total.")
        if overrides.land_rent_per_acre is not None:
            notes.append("Land rent is not added separately: it is part of the farmer's total cost.")
    else:
        credit = 0.0
        if req.crop == ProfitCrop.corn and (req.previous_crop or "").strip().lower() == "soybeans":
            credit = t.NITROGEN_CREDIT_LB_PER_ACRE * t.NITROGEN_PRICE_PER_LB
        for name, amount in t.COSTS[key].items():
            source = "baseline"
            if name == "fertilizer" and credit:
                amount = max(0.0, amount - credit)
                source = "baseline_with_nitrogen_credit"
                notes.append(
                    f"Fertilizer lowered by {_money(credit)}/acre: corn after soybeans needs about "
                    f"{_num(t.NITROGEN_CREDIT_LB_PER_ACRE)} lb less nitrogen per acre "
                    f"(at {_money(t.NITROGEN_PRICE_PER_LB)}/lb)."
                )
            costs.append(ProfitCostItem(
                key=name, label=t.COST_LABELS[name], amount_per_acre=round(amount, 2), source=source,
            ))
        if overrides.land_rent_per_acre is not None:
            rent, rent_source = overrides.land_rent_per_acre, "farmer"
            rent_note = "the farmer's figure"
        else:
            rent, rent_source = t.LAND_RENT[req.state], "baseline"
            rent_note = f"a typical {req.state.value} cash rent"
        costs.append(ProfitCostItem(
            key="land_rent", label=t.COST_LABELS["land_rent"],
            amount_per_acre=round(rent, 2), source=rent_source,
        ))
        breakdown = " + ".join(f"{c.label.lower()} {_money(c.amount_per_acre)}" for c in costs)
        notes.append(f"Land rent = {_money(rent)}/acre, {rent_note}.")
        notes.append(f"Costs = {breakdown} = {_money(sum(c.amount_per_acre for c in costs))}/acre.")
    total_cost = round(sum(c.amount_per_acre for c in costs), 2)

    # Scenarios: only the price changes.
    def scenario(price: float) -> ProfitScenario:
        revenue = round(yld * price, 2)
        return ProfitScenario(
            price=price, revenue_per_acre=revenue, cost_per_acre=total_cost,
            profit_per_acre=round(revenue - total_cost, 2),
        )

    low, base, high = (scenario(p) for p in t.PRICES[req.crop])
    notes.append(
        f"Prices are fixed reference values, not a forecast: low {_money(low.price)}, "
        f"base {_money(base.price)}, high {_money(high.price)} per {unit}."
    )
    notes.append(
        f"Revenue = {_num(yld)} {unit} × {_money(base.price)} = {_money(base.revenue_per_acre)} (base price)."
    )
    notes.append(
        f"Profit = {_money(base.revenue_per_acre)} − {_money(total_cost)} = "
        f"{_money(base.profit_per_acre)}/acre (base price); range {_money(low.profit_per_acre)} "
        f"to {_money(high.profit_per_acre)}."
    )
    if t.IS_PLACEHOLDER:
        notes.append("Baseline prices, yields and costs are placeholders, not USDA data. Illustration only.")

    return ProfitEstimate(
        crop=req.crop, state=req.state, yield_per_acre=yld, yield_unit=unit, yield_source=yield_source,
        costs=costs, scenarios=ProfitScenarios(low=low, base=base, high=high), assumptions=notes,
        baseline=ProfitBaselineInfo(version=t.BASELINE_VERSION, is_placeholder=t.IS_PLACEHOLDER),
    )
