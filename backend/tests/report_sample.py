"""An analysis result like the PDF design's example (Polk County, IA), for report tests and previews."""

import math
from datetime import UTC, date, datetime, timedelta

from app.models import AnalysisOptions, AnalysisResult

M3 = {"dataset": "SMAP L3 Enhanced Soil Moisture", "provider": "NASA"}
POWER = {"dataset": "NASA POWER", "provider": "NASA"}
SSURGO = {"dataset": "gSSURGO", "provider": "USDA NRCS"}
DEP = {"dataset": "3DEP elevation", "provider": "USGS"}
CSB = {"dataset": "USDA Crop Sequence Boundaries", "provider": "USDA"}

JOB_ID = "7c1e4a2b-0000-4000-8000-000000000001"


def metric(key, label, category, value, unit, quality, source, res, **kw):
    return {
        "key": key,
        "label": label,
        "category": category,
        "value": value,
        "unit": unit,
        "quality": quality,
        "source": source,
        "resolution_m": res,
        **kw,
    }


def strategy(
    sid, name, score, conf, current, seasons, topics, summary, evidence, good, watch, gaps, review=False
):
    crit = ["water_use", "soil_health", "erosion", "nitrogen", "pest_cycle", "income", "climate_risk"]
    return {
        "id": sid,
        "name": name,
        "is_current": current,
        "score": score,
        "confidence": conf,
        "rotation": [{"season_index": i, "crop": c, "role": r} for i, (c, r) in enumerate(seasons)],
        "score_breakdown": [{"criterion": c, "score": s} for c, s in zip(crit, topics, strict=True)],
        "summary": summary,
        "benefits": good,
        "risks": watch,
        "information_gaps": gaps,
        "evidence": [{"statement": s, "source": src} for s, src in evidence],
        "needs_local_review": review,
    }


def weekly(start: date, n: int, f) -> list[dict]:
    return [{"t": (start + timedelta(days=7 * i)).isoformat(), "v": f(i)} for i in range(n)]


def sample_result(**overrides) -> AnalysisResult:
    asof = "2026-11-12"
    data = {
        "selection": {
            "field_id": "csb2025_190000123456",
            "anchor": {"lat": 41.5868, "lon": -93.625},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-93.63, 41.58], [-93.62, 41.58], [-93.62, 41.59], [-93.63, 41.58]]],
            },
            "bbox": [-93.63, 41.58, -93.62, 41.59],
            "resolved_by": "field_polygon",
            "boundary_type": "estimated_csb",
            "area_ha": 32.37,
            "county": {"fips": "19153", "name": "Polk", "state_postal": "IA"},
            "source": "map_click",
            "crop_history": [
                {"year": 2025, "crop": "Corn"},
                {"year": 2024, "crop": "Soybeans"},
                {"year": 2023, "crop": "Corn"},
            ],
        },
        "generated_at": datetime(2026, 11, 15, 9, 30, tzinfo=UTC),
        "model_version": "rotation-v0.1",
        "current_conditions": [
            metric(
                "sm_surface",
                "Soil moisture (surface)",
                "moisture",
                0.27,
                "m3/m3",
                "measured",
                M3,
                9000,
                as_of=asof,
            ),
            metric(
                "sm_root",
                "Soil moisture (root zone)",
                "moisture",
                0.31,
                "m3/m3",
                "modeled",
                {"dataset": "SMAP L4", "provider": "NASA"},
                9000,
                as_of=asof,
            ),
            metric("rh", "Relative humidity", "atmosphere", 68, "%", "modeled", POWER, 50000, as_of=asof),
            metric(
                "t30",
                "Air temperature (30-day mean)",
                "temperature",
                13.9,
                "degC",
                "modeled",
                POWER,
                50000,
                period={"start": "2026-10-13", "end": asof},
            ),
            metric(
                "rain30",
                "Rain, last 30 days",
                "precipitation",
                40.6,
                "mm",
                "modeled",
                POWER,
                50000,
                period={"start": "2026-10-13", "end": asof},
            ),
            metric("som", "Soil organic matter", "soil", 3.8, "%", "measured", SSURGO, 30),
            metric(
                "n",
                "Soil nitrogen (total)",
                "soil",
                1.9,
                "g/kg",
                "estimated",
                SSURGO,
                30,
                note="Estimated from organic matter. Not a soil lab test.",
            ),
            metric("ph", "Soil pH", "soil", 6.4, "pH", "measured", SSURGO, 30),
            metric("tex", "Soil texture", "soil", "Silty clay loam", "class", "measured", SSURGO, 30),
            metric("elev", "Elevation", "terrain", 285.9, "m", "measured", DEP, 10),
            metric("slope", "Slope", "terrain", 2.1, "%", "measured", DEP, 10),
            metric(
                "ndvi",
                "Plant greenness (NDVI)",
                "vegetation",
                None,
                "none",
                "unavailable",
                {"dataset": "HLS", "provider": "NASA"},
                30,
                unavailable_reason="No cloud-free satellite pass in the last 14 days.",
            ),
        ],
        "time_series": [
            {
                "key": "soil_moisture_surface",
                "label": "Surface soil moisture",
                "unit": "m3/m3",
                "source": {"dataset": "SMAP L3", "provider": "NASA", "resolution_m": 9000},
                "points": weekly(
                    date(2026, 5, 14), 26, lambda i: round(0.3 + 0.07 * math.sin(i / 3) - 0.002 * i, 3)
                ),
            },
            {
                "key": "precip_weekly",
                "label": "Rain per week",
                "unit": "mm",
                "source": {"dataset": "NASA POWER", "provider": "NASA", "resolution_m": 50000},
                "points": weekly(
                    date(2026, 5, 14), 26, lambda i: [3, 0, 24, 25, 0, 27, 20, 5, 36, None][i % 10]
                ),
            },
        ],
        "strategies": [
            strategy(
                "rye",
                "Corn / soybean with winter rye cover",
                82,
                "high",
                False,
                [("Soybeans", "cash_crop"), ("Corn", "cash_crop"), ("Winter rye", "cover_crop")],
                [78, 90, 88, 70, 75, 72, 80],
                "Keeps your two main crops and adds a rye cover after harvest. It protects the soil "
                "and holds "
                "water, for a small extra cost.",
                [
                    ("Slope is 2.1 percent, where cover crops cut soil loss at low cost.", DEP),
                    (
                        "Surface soil moisture is 0.27 m³/m³ and has been falling, "
                        "so ground cover helps keep water.",
                        M3,
                    ),
                ],
                ["Less soil washed away on sloping ground", "Holds more water through dry spells"],
                ["Seed and seeding add cost", "Rye has to be ended on time in spring"],
                ["Your seeding and harvest dates are not known."],
            ),
            strategy(
                "cc",
                "Corn / soybean (your current rotation)",
                64,
                "high",
                True,
                [("Corn", "cash_crop"), ("Soybeans", "cash_crop")],
                [62, 55, 58, 60, 52, 80, 70],
                "The baseline. Strong yearly income, but the soil is bare after harvest.",
                [("Mapped crops for 2023 to 2025 are corn, soybeans and corn.", CSB)],
                ["Strong yearly income"],
                ["Soil is bare between harvest and planting"],
                ["Yields from past years are not included."],
            ),
            strategy(
                "alf",
                "Corn / soybean / alfalfa for forage",
                70,
                "low",
                False,
                [
                    ("Corn", "cash_crop"),
                    ("Soybeans", "cash_crop"),
                    ("Alfalfa", "forage"),
                    ("Alfalfa", "forage"),
                ],
                [66, 84, 90, 86, 88, 48, 60],
                "Two years of alfalfa rebuild the soil and fix nitrogen.",
                [("Soil organic matter is 3.8 percent, a good base for a deep-rooted forage.", SSURGO)],
                ["Strongest soil cover of the options"],
                ["Needs hay equipment and a buyer"],
                ["No hay or livestock market data for your county."],
                review=True,
            ),
            strategy(
                "oat",
                "Corn / soybean / oats with red clover",
                77,
                "medium",
                False,
                [
                    ("Corn", "cash_crop"),
                    ("Soybeans", "cash_crop"),
                    ("Oats", "cash_crop"),
                    ("Red clover", "nitrogen_fixer"),
                ],
                [74, 86, 80, 88, 90, 62, 76],
                "Adds oats and a clover that puts nitrogen back in the soil.",
                [("Your mapped crops repeat corn and soybeans, so a third crop breaks the cycle.", CSB)],
                ["Clover adds nitrogen for the next crop"],
                ["Lower income in the oat year"],
                ["Local oat prices are not included."],
            ),
        ],
        "datasets_used": [
            {**M3, "resolution_m": 9000, "coverage_period": "2015–2026"},
            {**POWER, "resolution_m": 50000, "coverage_period": "1981–2026"},
            {**SSURGO, "resolution_m": 30, "coverage_period": "Current release"},
            {**DEP, "resolution_m": 10, "coverage_period": "Current release"},
            {**CSB, "resolution_m": 30, "coverage_period": "2018–2025"},
        ],
        "warnings": [
            "Soil moisture and weather values cover areas much larger than this field, "
            "so treat them as local "
            "context.",
            "Crop history before 2023 is missing, so older rotations were not considered.",
        ],
        "disclaimer": "This tool supports your decisions. It does not replace a local agronomist "
        "or your county "
        "extension office, so check any change to your rotation with them first.",
    }
    data.update(overrides)
    return AnalysisResult.model_validate(data)


def sample_options(**kw) -> AnalysisOptions:
    return AnalysisOptions.model_validate({"horizon_years": 3, **kw})
