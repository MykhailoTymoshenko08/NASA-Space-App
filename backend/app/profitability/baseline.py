"""Static baseline tables for the profitability estimate. Edit the numbers here; no code changes needed.

!!! PLACEHOLDER VALUES !!!
Every number below is a rough, round placeholder, NOT sourced data. Replace each table with real
numbers and then set `IS_PLACEHOLDER = False` and bump `BASELINE_VERSION`. Suggested sources:

- DEFAULT_YIELD:  USDA NASS Quick Stats, yield per harvested acre by state (e.g. 5-year average).
- PRICES:         USDA ERS / WASDE season-average farm price (base); low/high = a band around it.
- COSTS:          Iowa State Ag Decision Maker (IA), Univ. of Illinois farmdoc crop budgets (IL),
                  UNL crop budgets (NE), or USDA ERS Commodity Costs and Returns by region.
- LAND_RENT:      USDA NASS Cash Rents survey, cropland rent per acre by state.
- NITROGEN_CREDIT_*: state N-rate guidance (e.g. ISU / Illinois MRTN) and current N price.

Units: yields in bushels per acre; prices in $ per bushel; costs in $ per acre.
"""

from app.models import ProfitCrop, ProfitState

BASELINE_VERSION = "placeholder-2026-11"
IS_PLACEHOLDER = True

C, S, W = ProfitCrop.corn, ProfitCrop.soybeans, ProfitCrop.winter_wheat
IA, IL, NE = ProfitState.IA, ProfitState.IL, ProfitState.NE

YIELD_UNIT = {C: "bu", S: "bu", W: "bu"}

# PLACEHOLDER: default yield (bu/acre) when the ML model gives none.
DEFAULT_YIELD: dict[tuple[ProfitCrop, ProfitState], float] = {
    (C, IA): 200, (S, IA): 58, (W, IA): 65,
    (C, IL): 205, (S, IL): 62, (W, IL): 80,
    (C, NE): 185, (S, NE): 60, (W, NE): 50,
}

# PLACEHOLDER: price per bushel as (low, base, high). Same for all three states.
PRICES: dict[ProfitCrop, tuple[float, float, float]] = {
    C: (3.80, 4.30, 4.90),
    S: (9.50, 10.50, 11.50),
    W: (4.80, 5.50, 6.30),
}

# PLACEHOLDER: operating costs ($/acre) per crop and state, without land rent.
# "other_operating" = fuel, repairs, drying, crop insurance, interest, machinery.
COSTS: dict[tuple[ProfitCrop, ProfitState], dict[str, float]] = {
    (C, IA): {"seed": 120, "fertilizer": 150, "chemicals": 60, "other_operating": 200},
    (S, IA): {"seed": 70, "fertilizer": 45, "chemicals": 55, "other_operating": 120},
    (W, IA): {"seed": 40, "fertilizer": 90, "chemicals": 35, "other_operating": 110},
    (C, IL): {"seed": 125, "fertilizer": 160, "chemicals": 65, "other_operating": 210},
    (S, IL): {"seed": 72, "fertilizer": 45, "chemicals": 58, "other_operating": 125},
    (W, IL): {"seed": 42, "fertilizer": 95, "chemicals": 35, "other_operating": 115},
    (C, NE): {"seed": 115, "fertilizer": 145, "chemicals": 55, "other_operating": 230},
    (S, NE): {"seed": 68, "fertilizer": 40, "chemicals": 50, "other_operating": 130},
    (W, NE): {"seed": 35, "fertilizer": 70, "chemicals": 30, "other_operating": 95},
}

# PLACEHOLDER: cash rent for cropland ($/acre), per state.
LAND_RENT: dict[ProfitState, float] = {IA: 270, IL: 280, NE: 230}

# PLACEHOLDER: corn after soybeans needs less nitrogen. Credit = lb N/acre x $/lb N.
NITROGEN_CREDIT_LB_PER_ACRE = 40
NITROGEN_PRICE_PER_LB = 0.60

COST_LABELS = {
    "seed": "Seed",
    "fertilizer": "Fertilizer",
    "chemicals": "Herbicide and pesticide",
    "other_operating": "Fuel, repairs, insurance and other",
    "land_rent": "Land rent",
    "total": "Total cost (farmer's figure)",
}
