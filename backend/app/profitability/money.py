"""Decimal rounding at monetary boundaries; JSON continues to use numbers in USD.

Round line items and revenues to cents with ROUND_HALF_UP. Derive profit by subtraction
of those displayed amounts. Scale field revenue and cost separately, then subtract so the
field totals reconcile too. Keep area and yield precision until the monetary boundary.
"""

from decimal import ROUND_HALF_UP, Decimal, localcontext
from math import isfinite

ACRES_PER_HECTARE = 10000 / 4046.8564224
CENT = Decimal("0.01")


def money(value: float | Decimal) -> float:
    return float(Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP))


def add(*values: float) -> float:
    return money(sum((Decimal(str(v)) for v in values), Decimal(0)))


def multiply(left: float, right: float) -> float:
    return money(Decimal(str(left)) * Decimal(str(right)))


def divide(value: float, divisor: float) -> float:
    return money(Decimal(str(value)) / Decimal(str(divisor)))


def break_even(cost: float, quantity: float) -> float | None:
    """Undefined or unrepresentable ratios remain null instead of failing JSON serialization."""
    if quantity == 0:
        return None
    with localcontext() as context:
        # Covers the entire finite float exponent range, including subnormal inputs.
        context.prec = 400
        value = divide(cost, quantity)
    return value if isfinite(value) else None


def field_amounts(revenue: float, cost: float, acres: float | None) -> dict[str, float | None]:
    if acres is None:
        return dict(field_revenue=None, field_cost=None, field_profit=None)
    field_revenue, field_cost = multiply(revenue, acres), multiply(cost, acres)
    return dict(field_revenue=field_revenue, field_cost=field_cost,
                field_profit=add(field_revenue, -field_cost))
