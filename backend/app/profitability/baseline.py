"""Static baseline tables for the profitability estimate, loaded from `baseline_data.json`.

The JSON is written by `scripts/build_profit_baseline.py` from USDA NASS reports and 2026 extension crop
budgets (ISU, farmdoc, UNL). Every entry carries its source and retrieval date, or `"placeholder": true`
with a reason. Rerun the script to refresh; the API only reads the file, with no external calls.

Units: yields in bushels per acre; prices in $ per bushel; costs in $ per acre.
"""

import json
from pathlib import Path

from app.models import DatasetRef, ProfitCrop, ProfitState

DATA_FILE = Path(__file__).with_name("baseline_data.json")
DATA = json.loads(DATA_FILE.read_text())

BASELINE_VERSION: str = DATA["version"]

C, S, W = ProfitCrop.corn, ProfitCrop.soybeans, ProfitCrop.winter_wheat
YIELD_UNIT = {C: "bu", S: "bu", W: "bu"}

_KEYS = [(c, s) for c in ProfitCrop for s in ProfitState]


def _entry(table: str, crop: ProfitCrop, state: ProfitState) -> dict:
    return DATA[table][crop.value][state.value]


# Default yield (bu/acre) when the ML model gives none.
DEFAULT_YIELD: dict[tuple[ProfitCrop, ProfitState], float] = {
    k: float(_entry("default_yield", *k)["value"]) for k in _KEYS
}

# Price per bushel as (low, base, high), per crop and state.
PRICES: dict[tuple[ProfitCrop, ProfitState], tuple[float, float, float]] = {
    k: tuple(float(_entry("prices", *k)[p]) for p in ("low", "base", "high")) for k in _KEYS
}

# Costs ($/acre) per crop and state, without land rent.
# "other_operating" = machinery, fuel, repairs, drying, crop insurance, labor, interest and overhead.
COST_KEYS = ("seed", "fertilizer", "chemicals", "other_operating")
COSTS: dict[tuple[ProfitCrop, ProfitState], dict[str, float]] = {
    k: {name: float(_entry("costs", *k)[name]) for name in COST_KEYS} for k in _KEYS
}


def cost_entry(crop: ProfitCrop, state: ProfitState, previous_crop: str | None = None) -> dict:
    entry = _entry("costs", crop, state)
    if (previous_crop or "").strip().lower() in {"soybean", "soybeans"}:
        return entry.get("after_soybeans", entry)
    return entry

# Cash rent for cropland ($/acre), per state.
LAND_RENT: dict[ProfitState, float] = {s: float(DATA["land_rent"][s.value]["value"]) for s in ProfitState}

# Corn after soybeans needs less nitrogen. Credit = lb N/acre x $/lb N.
NITROGEN_CREDIT_LB_PER_ACRE: float = float(DATA["nitrogen_credit"]["lb_per_acre"])
NITROGEN_PRICE_PER_LB: float = float(DATA["nitrogen_price"]["usd_per_lb"])

# Which inputs are still placeholders, e.g. ("prices", "Winter Wheat", "IA") or ("land_rent", "IA").
PLACEHOLDERS: set[tuple[str, ...]] = {
    (table, c.value, s.value)
    for table in ("prices", "default_yield", "costs") for c, s in _KEYS
    if _entry(table, c, s).get("placeholder")
} | {("land_rent", s.value) for s in ProfitState if DATA["land_rent"][s.value].get("placeholder")}
IS_PLACEHOLDER = bool(PLACEHOLDERS)


def source_ref(entry: dict) -> DatasetRef | None:
    source = entry.get("source")
    if not source or entry.get("placeholder"):
        return None
    document = source["document"]
    if source.get("table"):
        document += "; " + source["table"]
    return DatasetRef(dataset=document, provider=source["publisher"], url=source["url"],
                      coverage_period=entry.get("data_years", str(source["year"])))


COST_LABELS = {
    "seed": "Seed",
    "fertilizer": "Fertilizer",
    "chemicals": "Herbicide and pesticide",
    "other_operating": "Machinery, fuel, insurance and other",
    "land_rent": "Land rent",
    "total": "Total cost (farmer's figure)",
}
