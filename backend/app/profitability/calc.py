"""Profit per acre = yield x price - costs, at a low / base / high price. Pure: no I/O, no globals mutated.

The tables come from `app.profitability.baseline`; tests may pass their own via `tables`.
Unknown inputs withhold scenarios. Farmer inputs can replace every baseline independently.
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
from app.profitability.money import ACRES_PER_HECTARE, add, break_even, field_amounts, money, multiply


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
    missing: list[str] = []
    sources = []
    crop, state = req.crop.value, req.state.value
    entry = t.cost_entry(req.crop, req.state, req.previous_crop)
    has_rotation_profile = entry is not t.DATA["costs"][crop][state]
    overrides = req.cost_overrides
    baseline_costs = (overrides.total_cost_per_acre is None
                      and any(getattr(overrides, name) is None for name in t.COST_KEYS))
    acres = req.area_ha * ACRES_PER_HECTARE if req.area_ha is not None else None

    def use(value: dict, name: str, replacement: str) -> bool:
        if value.get("placeholder"):
            missing.append(f"No sourced {name} for {crop} / {state}. Supply {replacement}. "
                           + value["placeholder_reason"])
            return False
        source = default_tables.source_ref(value)
        if source and source not in sources:
            sources.append(source)
        return True

    # Yield
    yld, yield_source = None, "unavailable"
    if req.yield_per_acre is not None:
        yld, yield_source = req.yield_per_acre, "farmer"
        notes.append(f"Yield = {_num(yld)} {unit}/acre, the farmer's assumption.")
    elif req.predicted_yield is not None:
        yld, yield_source = req.predicted_yield, "model"
        notes.append(f"Yield = {_num(yld)} {unit}/acre, from the yield model.")
    elif (baseline_costs and not entry.get("placeholder")
          and entry.get("reference_yield_per_acre") is not None):
        use(entry, "yield", "yield_per_acre")
        yld, yield_source = float(entry["reference_yield_per_acre"]), "budget_reference"
        notes.append(f"Yield = {_num(yld)} {unit}/acre, matched to the published production-cost "
                     f"profile: {entry['source']['table']}. "
                     "This is a reference enterprise, not a field forecast.")
    elif use(t.DATA["default_yield"][crop][state], "yield", "yield_per_acre"):
        yld, yield_source = float(t.DEFAULT_YIELD[key]), "baseline_default"
        notes.append(f"Yield = {_num(yld)} {unit}/acre, a typical {crop} yield for {state} "
                     "(no model prediction given).")

    # Costs
    costs: list[ProfitCostItem] = []
    rent = None
    if overrides.total_cost_per_acre is not None:
        costs.append(ProfitCostItem(
            key="total", label=t.COST_LABELS["total"],
            amount_per_acre=money(overrides.total_cost_per_acre), source="farmer",
        ))
        notes.append(f"Costs = {_money(costs[0].amount_per_acre)}/acre, the farmer's own total.")
        notes.append("The farmer defines which cash and ownership costs this total includes. "
                     "Land is included but not itemized; return before land is unavailable.")
        if overrides.land_rent_per_acre is not None:
            notes.append("Land rent is not added separately: it is part of the farmer's total cost.")
    else:
        available_costs = not baseline_costs or use(
            entry, "production costs", "all itemized costs or total_cost_per_acre",
        )
        credit = 0.0
        if (available_costs and baseline_costs and not has_rotation_profile and req.crop == ProfitCrop.corn
                and overrides.fertilizer is None
                and (req.previous_crop or "").strip().lower() in {"soybean", "soybeans"}):
            credit = t.NITROGEN_CREDIT_LB_PER_ACRE * t.NITROGEN_PRICE_PER_LB
            use(t.DATA["nitrogen_credit"], "nitrogen credit", "fertilizer")
            use(t.DATA["nitrogen_price"], "nitrogen price", "fertilizer")
        if has_rotation_profile and baseline_costs:
            notes.append("Published after-soybean budget already includes rotation effects; "
                         "no extra nitrogen credit is subtracted.")
        for name in t.COST_KEYS:
            amount = getattr(overrides, name)
            if amount is not None:
                source = "farmer"
            elif available_costs:
                amount = entry[name]
                source = "baseline_rotation" if has_rotation_profile else "baseline"
                if name == "fertilizer" and credit:
                    amount = max(0.0, amount - credit)
                    source = "baseline_with_nitrogen_credit"
                    notes.append(f"Fertilizer lowered by {_money(credit)}/acre for corn after soybeans.")
            else:
                continue
            costs.append(ProfitCostItem(key=name, label=t.COST_LABELS[name],
                                        amount_per_acre=money(amount), source=source))
        if overrides.land_rent_per_acre is not None:
            rent, rent_source = money(overrides.land_rent_per_acre), "farmer"
            rent_note = "the farmer's figure"
        elif use(t.DATA["land_rent"][state], "land cost", "land_rent_per_acre"):
            rent, rent_source = money(t.LAND_RENT[req.state]), "baseline"
            year = t.DATA["land_rent"][state]["data_years"]
            rent_note = f"the {year} {state} state reference, not a local lease quote"
        if rent is not None:
            costs.append(ProfitCostItem(key="land_rent", label=t.COST_LABELS["land_rent"],
                                        amount_per_acre=rent, source=rent_source))
            notes.append(f"Land rent = {_money(rent)}/acre, {rent_note}.")
        if available_costs:
            breakdown = " + ".join(f"{c.label.lower()} {_money(c.amount_per_acre)}" for c in costs)
            notes.append(f"Costs = {breakdown} = {_money(add(*(c.amount_per_acre for c in costs)))}/acre.")
        if baseline_costs:
            notes.append("Published costs include machinery ownership/depreciation, labor and overhead "
                         "allowances, not only cash paid this season. "
                         "Farmer lines replace their matching allowances.")
        else:
            notes.append("Production costs are farmer inputs; "
                         "the farmer defines their cash and ownership basis.")
    total_cost = add(*(c.amount_per_acre for c in costs))
    notes.append("Government and insurance payments are excluded. Economic return is not cash flow.")

    prices, price_source = None, "unavailable"
    if req.price_overrides is not None:
        prices = [req.price_overrides.low, req.price_overrides.base, req.price_overrides.high]
        price_source = "farmer"
        notes.append("Sale prices are the farmer's scenarios, not a market forecast.")
    elif use(t.DATA["prices"][crop][state], "price", "price_overrides"):
        prices, price_source = t.PRICES[key], "baseline"
        notes.append(f"Prices are recent {state} history, not a forecast: low {_money(prices[0])}, "
                     f"base {_money(prices[1])}, high {_money(prices[2])} per {unit}.")

    # Scenarios: only the price changes.
    def scenario(price: float) -> ProfitScenario:
        revenue = multiply(yld, price)
        return ProfitScenario(
            price=price, revenue_per_acre=revenue, cost_per_acre=total_cost,
            profit_per_acre=add(revenue, -total_cost),
            return_before_land_per_acre=add(revenue, -total_cost, rent) if rent is not None else None,
            break_even_yield_per_acre=break_even(total_cost, price),
            **field_amounts(revenue, total_cost, acres),
        )

    scenarios = None
    if not missing:
        low, base, high = (scenario(p) for p in prices)
        scenarios = ProfitScenarios(low=low, base=base, high=high)
        notes.append(f"Revenue = {_num(yld)} {unit} × {_money(base.price)} = "
                     f"{_money(base.revenue_per_acre)} (base price).")
        notes.append(f"Profit = {_money(base.revenue_per_acre)} − {_money(total_cost)} = "
                     f"{_money(base.profit_per_acre)}/acre (base price); range {_money(low.profit_per_acre)} "
                     f"to {_money(high.profit_per_acre)}.")
    else:
        notes.append("Unsourced placeholder values are not calculated. "
                     "Supply missing farm inputs to obtain a budget.")
    if acres is not None:
        notes.append("Field totals use supplied hectares converted to acres. "
                     "They are not a surveyed farmed area.")
    notes.append("USD amounts use decimal half-up rounding to cents. "
                 "Field profit is field revenue minus field cost.")

    return ProfitEstimate(
        crop=req.crop, state=req.state, yield_per_acre=yld, yield_unit=unit, yield_source=yield_source,
        costs=costs, scenarios=scenarios, assumptions=notes,
        baseline=ProfitBaselineInfo(version=t.BASELINE_VERSION, is_placeholder=bool(missing)),
        cost_profile=(entry.get("source", {}).get("table")
                      if baseline_costs and not entry.get("placeholder") else None),
        status="unavailable" if missing else "estimated", price_source=price_source,
        area_acres=acres, break_even_price_per_unit=break_even(total_cost, yld) if scenarios else None,
        missing_inputs=missing, sources=sources,
    )
