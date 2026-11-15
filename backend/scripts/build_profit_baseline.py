"""Build `app/profitability/baseline_data.json`, the static tables behind POST /profitability/estimate.

Run from `backend/`:  uv run python scripts/build_profit_baseline.py
The API never runs this; it only reads the JSON file this script writes.

What it does
- Prices (per state and crop): NASS "Crop Values Annual Summary" releases on USDA ESMIS, table
  "<crop> Price per Bushel and Value of Production" (marketing-year average price received).
  base = mean of the last BASE_YEARS marketing years; low / high = 10th / 90th percentile
  (linear interpolation) of the last RANGE_YEARS marketing years. For each year the newest release wins.
- Fallback yields: NASS "Crop Production Annual Summary" releases on ESMIS, state yield per harvested
  acre, mean of the last YIELD_YEARS years.
- Costs: transcribed by hand from the 2026 extension crop budgets listed in BUDGETS (PDFs, so not parsed
  here). Each line keeps the page and the budget line items it is built from.
- Nitrogen credit: UNL EC117 Table I; nitrogen price: ISU FM 1712 (A1-20) 2026.
- Land rent: pinned verified state references in `rent_reference.json`; optional Quick Stats updates
  use a free API key in NASS_API_KEY (https://quickstats.nass.usda.gov/api). Without a key, verified
  references retain their original source and year. Nebraska uses dryland rent, not mixed cropland.
  Never commit the key; put it in backend/.env (gitignored) or export it in your shell.

Anything that cannot be sourced stays in the file with "placeholder": true and a reason.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import statistics
import sys
import urllib.parse
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "app" / "profitability" / "baseline_data.json"
CACHE = BACKEND / ".cache" / "profit_baseline"
UA = {"User-Agent": "field-shift-baseline-script"}
ESMIS = "https://esmis.nal.usda.gov/sites/default/release-files"

BASE_YEARS = 3
RANGE_YEARS = 10
YIELD_YEARS = 5

STATES = {"IA": "Iowa", "IL": "Illinois", "NE": "Nebraska"}
CROPS = ["Corn", "Soybeans", "Winter Wheat"]

# Newest first. Each Crop Values release has 3 marketing years; each Crop Production Annual has 3 years.
CROP_VALUES = [
    ("2026-02", f"{ESMIS}/795791/cpvl0226.zip"),
    ("2025-02", f"{ESMIS}/k35694332/4m90gs04k/5h73rr79v/cpvl0225.zip"),
    ("2024-02", f"{ESMIS}/k35694332/g158d382b/gm80kj25n/cpvl0224.zip"),
    ("2023-02", f"{ESMIS}/k35694332/b85171637/34850w190/cpvl0223.zip"),
    ("2022-02", f"{ESMIS}/k35694332/gb19g8865/g732fc89g/cpvl0222.zip"),
    ("2021-02", f"{ESMIS}/k35694332/348509606/qv33sq58w/cpvl0221.zip"),
    ("2020-02", f"{ESMIS}/k35694332/9w032m10t/76537j56z/cpvl0220.zip"),
    ("2019-04", f"{ESMIS}/k35694332/g445cn37b/m039kd38h/cpvl0419.zip"),
]
CROP_PRODUCTION = [
    ("2026-01", f"{ESMIS}/795725/cropan26.zip"),
    ("2024-01", f"{ESMIS}/k3569432s/ns065v292/br86cq93r/cropan24.zip"),
]
PRICE_TABLE = {
    "Corn": r"^Corn for Grain Price per Bushel",
    "Soybeans": r"^Soybeans for Beans Price per Bushel",
    "Winter Wheat": r"^Winter Wheat Price per Bushel",
}
YIELD_TABLE = {
    "Corn": r"^Corn Area Planted for All Purposes and Harvested for Grain, Yield",
    "Soybeans": r"^Soybeans for Beans Area Planted and Harvested, Yield",
    "Winter Wheat": r"^Winter Wheat Area Planted and Harvested, Yield",
}

ISU = {
    "publisher": "Iowa State University Extension and Outreach (Ag Decision Maker)",
    "document": "Estimated Costs of Crop Production in Iowa - 2026, FM 1712 / File A1-20, "
                "revised January 2026",
    "url": "https://www.extension.iastate.edu/agdm/crops/pdf/a1-20_2026.pdf",
    "year": 2026,
}
FARMDOC = {
    "publisher": "University of Illinois, farmdoc (Schnitkey and Paulson)",
    "document": "2026 Crop Budgets, revised May 2026, Table 2: Central Illinois - High Productivity Farmland",
    "url": "https://farmdoc.illinois.edu/assets/management/crop-budgets/crop_budgets_2026_May.pdf",
    "year": 2026,
}
UNL = {
    "publisher": "University of Nebraska-Lincoln, Center for Agricultural Profitability",
    "document": "2026 Nebraska Crop Budgets",
    "url": "https://cap.unl.edu/sites/unl.edu.ianr.agecon.center-for-ag-profitability/files/media/file/"
           "2026-nebraska-crop-budgets-r_0.pdf",
    "year": 2026,
}

# Costs in USD/acre, copied from the budgets. `other` lists every non-land line not in seed, fertilizer or
# chemicals; other_operating is their sum. Corn-after-corn is the standard profile; published
# after-soybean profiles below replace the full cost and yield pair when the predecessor is known.
BUDGETS = {
    ("Corn", "IA"): (ISU, "p. 2, Corn Following Corn, middle column (193 bu/acre)", {
        "seed": {"Seed": 113.70},
        "fertilizer": {"Nitrogen": 102.82, "Phosphate": 51.84, "Potash": 22.62, "Lime": 3.72},
        "chemicals": {"Herbicide": 56.00, "Insecticide": 25.00},
        "other": {"Preharvest machinery fixed": 41.20, "Preharvest machinery variable": 30.10,
                  "Crop insurance": 17.10, "Miscellaneous": 13.70, "Interest": 21.74,
                  "Harvest machinery fixed": 64.71, "Harvest machinery variable": 64.65, "Labor": 57.12},
    }),
    ("Soybeans", "IA"): (ISU, "p. 5, Herbicide Tolerant Soybeans Following Corn, middle column (61 bu)", {
        "seed": {"Seed": 63.10},
        "fertilizer": {"Phosphate": 35.28, "Potash": 35.88, "Lime": 3.72},
        "chemicals": {"Herbicide": 75.00},
        "other": {"Preharvest machinery fixed": 37.60, "Preharvest machinery variable": 26.60,
                  "Crop insurance": 9.10, "Miscellaneous": 13.70, "Interest": 13.07,
                  "Harvest machinery fixed": 32.42, "Harvest machinery variable": 14.76, "Labor": 44.88},
    }),
    ("Corn", "IL"): (FARMDOC, "Table 2, Corn-after-Corn (231 bu/acre)", {
        "seed": {"Seed": 129}, "fertilizer": {"Fertilizers": 239}, "chemicals": {"Pesticides": 122},
        "other": {"Drying": 14, "Storage": 14, "Crop insurance": 31, "Total power costs": 181,
                  "Total overhead costs": 118},
    }),
    ("Soybeans", "IL"): (FARMDOC, "Table 2, Soybeans-after-Corn (76 bu/acre)", {
        "seed": {"Seed": 83}, "fertilizer": {"Fertilizers": 66}, "chemicals": {"Pesticides": 70},
        "other": {"Drying": 0, "Storage": 8, "Crop insurance": 11, "Total power costs": 160,
                  "Total overhead costs": 113},
    }),
    ("Winter Wheat", "IL"): (FARMDOC, "Table 2, Wheat (89 bu/acre)", {
        "seed": {"Seed": 59}, "fertilizer": {"Fertilizers": 143}, "chemicals": {"Pesticides": 43},
        "other": {"Drying": 1, "Storage": 9, "Crop insurance": 17, "Total power costs": 140,
                  "Total overhead costs": 105},
    }),
    ("Corn", "NE"): (UNL, "p. 75, #020 Corn, Dryland, No Till, Continuous, Eastern Neb. (180 bu/acre)", {
        "seed": {"Seed": 114.06}, "fertilizer": {"Fertilizer": 139.60}, "chemicals": {"Pesticide": 95.49},
        "other": {"Custom services": 31.90, "Labor": 8.73, "Fuel and energy": 8.61,
                  "Repairs and maintenance": 12.53, "Other (insurance, scouting, drying)": 18.60,
                  "Interest on operating capital": 17.18, "General overhead": 28.00,
                  "Equipment depreciation": 47.31, "Equipment opportunity cost": 16.22},
    }),
    ("Soybeans", "NE"): (UNL, "p. 199, #060 Soybeans, Dryland, No Till after Corn (50 bu/acre)", {
        "seed": {"Seed": 82.00}, "fertilizer": {"Fertilizer": 0.00}, "chemicals": {"Pesticide": 61.02},
        "other": {"Custom services": 10.80, "Labor": 8.15, "Fuel and energy": 8.42,
                  "Repairs and maintenance": 12.27, "Other (insurance, scouting, materials)": 19.50,
                  "Interest on operating capital": 8.09, "General overhead": 28.00,
                  "Equipment depreciation": 40.50, "Equipment opportunity cost": 17.53},
    }),
    ("Winter Wheat", "NE"): (UNL, "p. 249, #075 Wheat, No Till, Southwest, after Row Crop (55 bu/acre)", {
        "seed": {"Seed": 36.90}, "fertilizer": {"Fertilizer": 90.50}, "chemicals": {"Pesticide": 12.13},
        "other": {"Custom services": 12.65, "Labor": 6.25, "Fuel and energy": 5.54,
                  "Repairs and maintenance": 5.39, "Other (insurance, scouting)": 18.00,
                  "Interest on operating capital": 7.49, "General overhead": 28.00,
                  "Equipment depreciation": 22.41, "Equipment opportunity cost": 7.50},
    }),
}

# Match each cost profile to its own published yield. State-average NASS yields remain useful
# context, but cannot be paired silently with a high-productivity or dryland enterprise budget.
BUDGET_YIELDS = {
    ("Corn", "IA"): 193, ("Soybeans", "IA"): 61,
    ("Corn", "IL"): 231, ("Soybeans", "IL"): 76, ("Winter Wheat", "IL"): 89,
    ("Corn", "NE"): 180, ("Soybeans", "NE"): 50, ("Winter Wheat", "NE"): 55,
}
AFTER_SOYBEANS = {
    ("Corn", "IA"): (ISU, "p. 3, Corn Following Soybeans, middle column (211 bu/acre)", 211, {
        "seed": {"Seed": 113.70},
        "fertilizer": {"Nitrogen": 84.27, "Phosphate": 56.88, "Potash": 24.57, "Lime": 3.72},
        "chemicals": {"Herbicide": 56.00},
        "other": {"Preharvest machinery fixed": 34.80, "Preharvest machinery variable": 24.60,
                  "Crop insurance": 17.10, "Miscellaneous": 13.70, "Interest": 19.65,
                  "Harvest machinery fixed": 67.56, "Harvest machinery variable": 69.41, "Labor": 52.02},
    }),
    ("Corn", "IL"): (FARMDOC, "Table 2, Corn-after-Soybeans (241 bu/acre)", 241, {
        "seed": {"Seed": 129}, "fertilizer": {"Fertilizers": 229}, "chemicals": {"Pesticides": 116},
        "other": {"Drying": 15, "Storage": 14, "Crop insurance": 31, "Total power costs": 181,
                  "Total overhead costs": 118},
    }),
    ("Soybeans", "IL"): (FARMDOC, "Table 2, Soybeans-after-Soybeans (74 bu/acre)", 74, {
        "seed": {"Seed": 83}, "fertilizer": {"Fertilizers": 66}, "chemicals": {"Pesticides": 75},
        "other": {"Drying": 0, "Storage": 8, "Crop insurance": 11, "Total power costs": 160,
                  "Total overhead costs": 113},
    }),
    ("Corn", "NE"): (UNL, "p. 87, #024 Corn, Dryland, No Till after Soybeans (195 bu/acre)", 195, {
        "seed": {"Seed": 105.01}, "fertilizer": {"Fertilizer": 116.50}, "chemicals": {"Pesticide": 97.10},
        "other": {"Custom services": 33.25, "Labor": 10.44, "Fuel and energy": 8.69,
                  "Repairs and maintenance": 13.89, "Other (insurance, scouting, drying)": 18.90,
                  "Interest on operating capital": 16.15, "General overhead": 28.00,
                  "Equipment depreciation": 52.94, "Equipment opportunity cost": 15.38},
    }),
}

NITROGEN_CREDIT = {
    "lb_per_acre": 45,
    "source": {
        "publisher": "University of Nebraska-Lincoln Extension",
        "document": "EC117 Nutrient Management Suggestions for Corn, revised December 2023",
        "table": "Table I, soybean, fine-medium textured soils (35 lb/acre on coarse soils)",
        "url": "https://extensionpublications.unl.edu/assets/pdf/ec117.pdf",
        "year": 2023,
    },
}
NITROGEN_PRICE = {
    "usd_per_lb": 0.53,
    "source": {**ISU, "table": "p. 2-3, corn budgets, line 'Nitrogen, $0.53 per pound'"},
}

PLACEHOLDERS = {
    # Last-resort values from the original placeholder tables, only where no source was found.
    "yield": {("Winter Wheat", "IA"): 65},
    "price": {("Winter Wheat", "IA"): (4.80, 5.50, 6.30)},
    "costs": {
        ("Winter Wheat", "IA"): {"seed": 40, "fertilizer": 90, "chemicals": 35, "other_operating": 110},
    },
    "land_rent": {"IA": 270, "IL": 280, "NE": 230},
}
IA_WHEAT_REASON = ("NASS does not publish Iowa winter wheat yield or price (Iowa is not an estimating state) "
                   "and ISU publishes no wheat budget.")


def fetch(url: str) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / url.rsplit("/", 1)[-1]
    if not path.exists():
        print(f"download {url}", file=sys.stderr)
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
            path.write_bytes(r.read())
    return path.read_bytes()


def tables(zip_bytes: bytes) -> list[tuple[str, list[list[str]]]]:
    """(title, rows) for every NASS table CSV in a release zip."""
    out = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in z.namelist():
            if not name.endswith(".csv") or "all_tables" in name:
                continue
            rows = list(csv.reader(io.StringIO(z.read(name).decode("latin-1"))))
            title = next((r[2] for r in rows[1:] if len(r) > 2 and r[1] == "t"), "")
            out.append((title.strip(), rows))
    return out


def state_values(rows: list[list[str]], label: str) -> dict[str, dict[int, float]]:
    """{state: {year: value}} for the columns whose header starts with `label`."""
    heads = [r for r in rows if len(r) > 1 and r[1] == "h"]
    labels = next((h for h in heads if any(c.startswith(label) for c in h)), None)
    years = next((h for h in heads if any(re.match(r"^\d{4}", c) for c in h[3:])), None)
    if not labels or not years:
        return {}
    cols = {i: int(years[i][:4]) for i in range(3, len(labels))
            if labels[i].startswith(label) and re.match(r"^\d{4}", years[i])}
    out: dict[str, dict[int, float]] = {}
    for r in rows:
        if len(r) > 3 and r[1] == "d" and r[2].strip() in STATES.values():
            for i, yr in cols.items():
                try:
                    out.setdefault(r[2].strip(), {})[yr] = float(r[i])
                except ValueError:
                    pass
    return out


def collect(releases, patterns, label):
    """{(crop, state_name): {year: (value, release, table_title)}}; newest release wins per year."""
    found: dict[tuple[str, str], dict[int, tuple[float, str, str]]] = {}
    for release, url in releases:
        for title, rows in tables(fetch(url)):
            for crop, pat in patterns.items():
                if re.search(pat, title):
                    for st, by_year in state_values(rows, label).items():
                        for yr, v in by_year.items():
                            found.setdefault((crop, st), {}).setdefault(yr, (v, release, title))
    return found


def percentile(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def releases_used(series: dict[int, tuple[float, str, str]], years: list[int]) -> list[str]:
    return sorted({series[y][1] for y in years}, reverse=True)


def build_prices(today: str) -> dict:
    data = collect(CROP_VALUES, PRICE_TABLE, "Price per bushel")
    out: dict = {}
    for crop in CROPS:
        for st, name in STATES.items():
            series = data.get((crop, name), {})
            if len(series) < RANGE_YEARS:
                lo, base, hi = PLACEHOLDERS["price"][(crop, st)]
                out.setdefault(crop, {})[st] = {
                    "low": lo, "base": base, "high": hi, "unit": "USD/bu",
                    "placeholder": True,
                    "placeholder_reason": IA_WHEAT_REASON if (crop, st) == ("Winter Wheat", "IA")
                    else f"only {len(series)} years of NASS prices found",
                }
                continue
            years = sorted(series)[-RANGE_YEARS:]
            base_years = years[-BASE_YEARS:]
            vals = [series[y][0] for y in years]
            entry = {
                "low": round(percentile(vals, 0.10), 2),
                "base": round(statistics.mean(series[y][0] for y in base_years), 2),
                "high": round(percentile(vals, 0.90), 2),
                "unit": "USD/bu",
                "data_years": f"{years[0]}-{years[-1]}",
                "base_years": f"{base_years[0]}-{base_years[-1]}",
                "history": {str(y): series[y][0] for y in years},
                "source": {
                    "publisher": "USDA NASS",
                    "document": "Crop Values Annual Summary (releases "
                                + ", ".join(releases_used(series, years)) + ")",
                    "table": series[years[-1]][2],
                    "url": "https://esmis.nal.usda.gov/publication/crop-values-annual-summary",
                    "year": years[-1],
                    "retrieved": today,
                    "note": f"Marketing-year average price received. {years[-1]} is preliminary.",
                },
            }
            assert entry["low"] < entry["base"] < entry["high"], (crop, st, entry)
            out.setdefault(crop, {})[st] = entry
    return out


def build_yields(today: str) -> dict:
    data = collect(CROP_PRODUCTION, YIELD_TABLE, "Yield per acre")
    out: dict = {}
    for crop in CROPS:
        for st, name in STATES.items():
            series = data.get((crop, name), {})
            if len(series) < YIELD_YEARS:
                out.setdefault(crop, {})[st] = {
                    "value": PLACEHOLDERS["yield"][(crop, st)], "unit": "bu/acre", "placeholder": True,
                    "placeholder_reason": IA_WHEAT_REASON if (crop, st) == ("Winter Wheat", "IA")
                    else f"only {len(series)} years of NASS yields found",
                }
                continue
            years = sorted(series)[-YIELD_YEARS:]
            out.setdefault(crop, {})[st] = {
                "value": round(statistics.mean(series[y][0] for y in years), 1),
                "unit": "bu/acre",
                "data_years": f"{years[0]}-{years[-1]}",
                "history": {str(y): series[y][0] for y in years},
                "source": {
                    "publisher": "USDA NASS",
                    "document": "Crop Production Annual Summary (releases "
                                + ", ".join(releases_used(series, years)) + ")",
                    "table": series[years[-1]][2],
                    "url": "https://esmis.nal.usda.gov/publication/crop-production-annual-summary",
                    "year": years[-1],
                    "retrieved": today,
                    "note": f"Mean state yield per harvested acre, {years[0]}-{years[-1]}.",
                },
            }
    return out


def build_costs(today: str) -> dict:
    out: dict = {}
    for crop in CROPS:
        for st in STATES:
            if (crop, st) not in BUDGETS:
                out.setdefault(crop, {})[st] = {
                    **PLACEHOLDERS["costs"][(crop, st)], "unit": "USD/acre",
                    "placeholder": True, "placeholder_reason": IA_WHEAT_REASON,
                }
                continue
            src, where, lines = BUDGETS[(crop, st)]
            entry = {k: round(sum(lines[k].values()), 2) for k in ("seed", "fertilizer", "chemicals")}
            entry["other_operating"] = round(sum(lines["other"].values()), 2)
            entry |= {
                "unit": "USD/acre",
                "data_years": str(src["year"]),
                "line_items": lines,
                "source": {**src, "table": where, "retrieved": today,
                           "note": "Non-land costs; land is a separate line."},
                "reference_yield_per_acre": BUDGET_YIELDS[(crop, st)],
            }
            if (crop, st) in AFTER_SOYBEANS:
                alt_src, alt_where, alt_yield, alt = AFTER_SOYBEANS[(crop, st)]
                entry["after_soybeans"] = {
                    **{k: round(sum(alt[k].values()), 2) for k in ("seed", "fertilizer", "chemicals")},
                    "other_operating": round(sum(alt["other"].values()), 2),
                    "unit": "USD/acre", "data_years": str(alt_src["year"]), "line_items": alt,
                    "reference_yield_per_acre": alt_yield,
                    "source": {**alt_src, "table": alt_where, "retrieved": today,
                               "note": "Non-land rotation budget; includes rotation effects. "
                                       "Do not subtract another nitrogen credit."},
                }
            out.setdefault(crop, {})[st] = entry
    return out


def build_land_rent(today: str) -> dict:
    key = os.environ.get("NASS_API_KEY", "").strip()
    references = json.loads((OUT.parent / "rent_reference.json").read_text())
    out: dict = {}
    for st in STATES:
        if not key:
            out[st] = references[st]
            continue
        q = {
            "key": key, "source_desc": "SURVEY", "sector_desc": "ECONOMICS", "agg_level_desc": "STATE",
            "state_alpha": st,
            "short_desc": "RENT, CASH, CROPLAND, NON-IRRIGATED - EXPENSE, MEASURED IN $ / ACRE",
            "format": "JSON",
        }
        url = "https://quickstats.nass.usda.gov/api/api_GET/?" + urllib.parse.urlencode(q)
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
            rows = json.load(r)["data"]
        rows = [r for r in rows if r["reference_period_desc"] == "YEAR"
                and r["Value"].replace(",", "").replace(".", "").strip().isdigit()]
        rows = [r for r in rows if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", r["Value"].replace(",", ""))]
        latest = max(rows, key=lambda r: int(r["year"]), default=None)
        if latest is None or int(latest["year"]) < int(references[st]["data_years"]):
            out[st] = references[st]
            continue
        out[st] = {
            "value": float(latest["Value"].replace(",", "")), "unit": "USD/acre",
            "data_years": str(latest["year"]),
            "source": {
                "publisher": "USDA NASS", "document": "Quick Stats, Cash Rents survey",
                "table": q["short_desc"], "url": "https://quickstats.nass.usda.gov/",
                "year": int(latest["year"]), "retrieved": today,
            },
        }
    return out


def main() -> None:
    today = date.today().isoformat()
    data = {
        "version": f"usda-extension-{today}-financial-v1",
        "generated": today,
        "generated_by": "backend/scripts/build_profit_baseline.py",
        "units": {"price": "USD/bu", "yield": "bu/acre", "costs": "USD/acre", "land_rent": "USD/acre",
                  "nitrogen_credit": "lb N/acre", "nitrogen_price": "USD/lb N"},
        "method": {
            "price": f"base = mean NASS marketing-year average price received over the last {BASE_YEARS} "
                     "years; "
                     f"low / high = 10th / 90th percentile (linear) over the last {RANGE_YEARS} years.",
            "yield": f"mean NASS state yield per harvested acre over the last {YIELD_YEARS} years.",
            "costs": "2026 extension enterprise budgets paired with their published reference yields; "
                     "after-soybean profiles include rotation effects with no additional nitrogen credit. "
                     "other_operating = all non-land lines except "
                     "seed, fertilizer and chemicals (machinery, fuel, repairs, drying, insurance, labor, "
                     "interest, overhead).",
        },
        "prices": build_prices(today),
        "default_yield": build_yields(today),
        "costs": build_costs(today),
        "land_rent": build_land_rent(today),
        "nitrogen_credit": {**NITROGEN_CREDIT, "unit": "lb N/acre",
                            "source": {**NITROGEN_CREDIT["source"], "retrieved": today}},
        "nitrogen_price": {**NITROGEN_PRICE, "unit": "USD/lb N", "data_years": "2026",
                           "source": {**NITROGEN_PRICE["source"], "retrieved": today}},
    }
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(BACKEND)}", file=sys.stderr)


if __name__ == "__main__":
    main()
