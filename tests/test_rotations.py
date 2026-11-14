"""tests for the rotation planner: detection, candidates, calculator, priorities, scenario, cover crops, stress rule."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml_service import agro
from ml_service.ranking import FieldContext, load_assets
from ml_service.rotations import PRIORITY_KEYS, detect_rotation, load_settings, plan_rotations
from ml_service.stress import StressSignal, compute_stress, peak_months, stress_multipliers

ROOT = Path(__file__).resolve().parent.parent
A = load_assets()
CFG = load_settings()

CLIMATE = dict(gdd_grow=1850.0, tmean_grow=19.5, tmax_summer=29.5, heat_days_32=14.0, heat_days_35=4.0, precip_grow=580.0,
               precip_spring=290.0, precip_summer=290.0, et0_grow=800.0, water_balance_grow=-220.0, max_dry_spell=11.0,
               extreme_rain_days_spring=2.0, extreme_rain_days_year=5.0, last_spring_frost_doy=112.0,
               first_fall_frost_doy=295.0, frost_free_days=183.0, srad_grow=20.5, rh_summer=68.0)
SOIL = dict(clay_pct=27.0, sand_pct=12.0, om_pct=3.5, soc_pct=2.0, ph_h2o=6.5, ec_ds_m=0.3, awc_cm_cm=0.2, kw_factor=0.3,
            hydgrp="C", drainage_class="Somewhat poorly drained", texture_class="Silt loam")
ET0 = [10, 15, 35, 70, 110, 140, 155, 135, 95, 55, 25, 12]
P = [28, 30, 55, 90, 120, 120, 105, 100, 80, 70, 55, 35]


def ctx(history=None, **kw) -> FieldContext:
    history = history or {2018 + i: ("corn" if i % 2 == 0 else "soybean") for i in range(8)}   # corn-soy, soybean in 2025
    base = dict(field_id="t1", state="IA", lat=41.9, lon=-93.6, prev_crops=[history[2025], history[2024]], soil=dict(SOIL),
                slope_pct=3.0, climate_norm=dict(CLIMATE), climate_lag1=dict(CLIMATE), winter_tmin_c=-24.0, history=history,
                target_year=2026, et0_monthly=list(ET0), precip_monthly=list(P), precip_annual=float(sum(P)), scenario=(0.0, 0.0))
    base.update(kw)
    return FieldContext(**base)


def hist(seq, start=2018):
    return {start + i: c for i, c in enumerate(seq)}


# ---------------------------------------------------------------- current rotation

def test_detect_clean_two_year_rotation():
    d = detect_rotation(hist(["corn", "soybean"] * 4), 2026, 3, CFG["rotation_detection"])
    assert d.cycle == ["corn", "soybean"] and d.steps == ["corn", "soybean", "corn"]
    assert d.clean and d.confidence >= 0.9 and d.period == 2 and d.years_used == [2018, 2025]


def test_detect_three_year_cycle_with_one_deviation():
    d = detect_rotation(hist(["corn", "corn", "corn", "soybean", "corn", "corn", "soybean", "corn"]), 2026, 3, CFG["rotation_detection"])
    assert d.period == 3 and d.clean and d.cycle == ["corn", "corn", "soybean"]   # written to end with the legume
    assert d.steps == ["corn", "soybean", "corn"]                                   # but continued from where the field is


def test_detect_recent_pattern_with_fallow_and_short_window():
    d = detect_rotation(hist(["winter_wheat", "fallow", "winter_wheat", "corn", "fallow", "winter_wheat", "fallow", "winter_wheat"]),
                        2026, 3, CFG["rotation_detection"])
    assert d.window == 4 and d.period == 2 and d.steps == ["fallow", "winter_wheat", "fallow"]
    assert d.confidence < 0.7                                                       # only 4 years support it


def test_detect_no_pattern_is_flagged():
    d = detect_rotation(hist(["corn", "soybean", "winter_wheat", "sorghum", "alfalfa", "oats", "corn", "barley"]), 2026, 3, CFG["rotation_detection"])
    assert not d.clean and d.confidence < 0.4


def test_detect_four_year_cycle_is_complete():
    d = detect_rotation(hist(["winter_wheat", "winter_wheat", "other", "sorghum", "soybean", "winter_wheat", "other", "sorghum"]),
                        2026, 3, CFG["rotation_detection"])
    assert d.period == 4 and len(d.cycle) == 4 and len(d.steps) == 3


def test_detect_without_history():
    assert detect_rotation({}, 2026, 3, CFG["rotation_detection"]).steps == ["unknown"] * 3


def test_fallow_and_double_crops_are_read_from_cdl_codes():
    from ml_service.cdl import DOUBLE_CROPS, history_token
    slug = {c["cdl_code"]: s for s, c in A.candidates.items()}
    assert history_token(61, slug) == "fallow" and history_token(1, slug) == "corn" and history_token(176, slug) == "other"
    assert history_token(26, slug) == "winter_wheat+soybean" and history_token(225, slug) == "winter_wheat+corn"
    assert history_token(228, slug) == "other+corn" and history_token(236, slug) == "winter_wheat+sorghum"
    assert history_token(229, slug) == "other" and history_token(227, slug) == "other"      # pumpkins and lettuce are NOT double crops
    assert all(len(v) == 2 for v in DOUBLE_CROPS.values())


def test_double_crop_year_in_the_current_rotation():
    from ml_service.feature_text import crop_name
    d = detect_rotation(hist(["corn", "soybean", "corn", "soybean", "corn", "winter_wheat+soybean", "corn", "winter_wheat+soybean"]),
                        2026, 3, CFG["rotation_detection"])
    assert d.period == 2 and d.steps == ["corn", "winter_wheat+soybean", "corn"]
    assert crop_name("winter_wheat+soybean", "uk") == "Озима пшениця / соя (подвійний посів)"
    assert crop_name("winter_wheat+soybean", "en") == "Winter wheat / soybean (double crop)" and crop_name("fallow", "uk") == "Пар"
    r = plan_rotations(ctx(hist(["corn", "soybean", "corn", "soybean", "corn", "winter_wheat+soybean", "corn", "winter_wheat+soybean"])), A)
    cur = r["strategies"][0]
    assert cur["name"] == "Поточна: Кукурудза – Озима пшениця / соя (подвійний посів)"
    years = {c["year"]: [x["crop"] for x in cur["sequence"] if x["year"] == c["year"]] for c in cur["sequence"]}
    assert years[2] == ["winter_wheat", "soybean"]                                    # two main crops in the same year


def test_double_crop_and_fallow_in_the_calculator():
    double = agro.profile("winter_wheat+soybean")
    wheat, soy = agro.CROPS["winter_wheat"], agro.CROPS["soybean"]
    assert double.n_fix == soy.n_fix and double.n_net == wheat.n_net + soy.n_net and double.legume
    assert double.kc[:6] == wheat.kc[:6] and double.kc[6:] == soy.kc[6:]
    fallow = calc(["winter_wheat", "fallow"], precip_annual=450.0)
    cropped = calc(["winter_wheat", "winter_wheat"], precip_annual=450.0)
    assert fallow.bare_days > cropped.bare_days and fallow.water_use_mm < cropped.water_use_mm
    assert calc(["fallow", "fallow", "corn"]).pest_break is True                      # fallow repeating is not a pest problem


# ---------------------------------------------------------------- the agro calculator

def calc(steps, covers=None, **kw):
    base = dict(et0_monthly=ET0, precip_annual=float(sum(P)), kw_factor=0.3, slope_pct=3.0, om_pct=3.5, awc=0.2)
    base.update(kw)
    return agro.evaluate(steps, covers or [False] * len(steps), "soybean", **base)


def test_cover_crop_effects():
    plain, covered = calc(["corn", "soybean", "corn"]), calc(["corn", "soybean", "corn"], [True] * 3)
    assert covered.bare_days < plain.bare_days * 0.6
    assert covered.erosion_t_ha < plain.erosion_t_ha * 0.7
    assert 30 < covered.water_use_mm - plain.water_use_mm < 130           # rye uses some spring water, not hundreds of mm
    assert covered.scores["soil_health"] > plain.scores["soil_health"] + 15


def test_nitrogen_and_pests():
    assert calc(["alfalfa"] * 3).n_net > 100 and calc(["alfalfa"] * 3).n_fixed == 150
    assert calc(["corn", "soybean", "corn"]).n_net < 0
    assert calc(["corn", "soybean", "corn"]).pest_break is True
    rep = calc(["corn", "corn", "soybean"])                                   # last year was soybean, then corn twice
    assert rep.pest_break is False and rep.pest_pairs == [("corn", "corn")]
    assert calc(["soybean", "soybean", "corn"]).pest_pairs[0] == ("soybean", "soybean")   # soybean after soybean (last year)
    assert calc(["alfalfa"] * 3, ).pest_break is True                         # a perennial stand is not a repeat


def test_rusle_monotonic():
    assert agro.rainfall_erosivity(900) > agro.rainfall_erosivity(600) > agro.rainfall_erosivity(400)
    assert agro.slope_factor(8) > agro.slope_factor(3) > agro.slope_factor(0.5)
    flat, steep = calc(["corn", "soybean", "corn"], slope_pct=1.0), calc(["corn", "soybean", "corn"], slope_pct=8.0)
    assert steep.erosion_t_ha > 2 * flat.erosion_t_ha
    assert calc(["corn", "soybean", "corn"], kw_factor=0.4).erosion_t_ha > calc(["corn", "soybean", "corn"], kw_factor=0.2).erosion_t_ha
    assert calc(["alfalfa"] * 3).erosion_t_ha < 0.2 * calc(["corn", "soybean", "corn"]).erosion_t_ha


def test_water_uses_et0_and_irrigation():
    hot = calc(["corn", "soybean", "corn"], et0_monthly=[e * 1.1 for e in ET0])
    assert hot.water_use_mm == pytest.approx(calc(["corn", "soybean", "corn"]).water_use_mm * 1.1, rel=1e-6)   # Kc x ET0
    dry = calc(["corn", "soybean", "corn"], precip_annual=600.0)
    assert dry.scores["water"] < calc(["corn", "soybean", "corn"]).scores["water"]
    assert calc(["corn", "soybean", "corn"], precip_annual=600.0, irrigated=True).scores["water"] > dry.scores["water"]


def test_scenario_hurts_heat_sensitive_crops_in_income():
    base, hot = calc(["corn", "soybean", "corn"]), calc(["corn", "soybean", "corn"], temp_delta_c=3.0, precip_change_pct=-30.0)
    assert hot.scores["income"] < base.scores["income"] - 5
    sorghum_drop = calc(["sorghum"] * 3).scores["income"] - calc(["sorghum"] * 3, temp_delta_c=3.0, precip_change_pct=-30.0).scores["income"]
    corn_drop = base.scores["income"] - hot.scores["income"]
    assert sorghum_drop < corn_drop                                            # sorghum is the tolerant one


# ---------------------------------------------------------------- the planner

def test_plan_matches_the_contract_format():
    r = plan_rotations(ctx(), A)
    ids = {s["id"] for s in r["strategies"]}
    assert r["strategies"][0]["id"] == "current" and r["strategies"][0]["is_current"] and r["strategies"][0]["delta_vs_current"] is None
    assert len(r["strategies"]) == 4 and len(ids) == 4
    src = {s["id"] for s in r["sources"]}
    keys = {"id", "is_current", "name", "sequence", "scores", "delta_vs_current", "metrics", "why", "evidence", "benefits",
            "risks", "data_gaps", "check_with_agronomist", "confidence"}
    for s in r["strategies"]:
        assert set(s) == keys
        assert set(s["scores"]) == {*PRIORITY_KEYS, "overall"} and all(0 <= v <= 100 for v in s["scores"].values())
        assert set(s["metrics"]) == {"water_use_mm_yr", "n_fixed_kg_ha_yr", "bare_days_yr", "erosion_t_ha_yr"}
        assert 0 <= s["confidence"] <= 1 and s["why"] and s["benefits"]
        assert {i["season"] for i in s["sequence"]} <= {"main", "cover"}
        for e in s["evidence"]:
            assert set(e["source_ids"]) <= src
        if not s["is_current"]:
            assert set(s["delta_vs_current"]) == set(s["scores"])
            assert all(s["delta_vs_current"][k] == s["scores"][k] - r["strategies"][0]["scores"][k] for k in s["scores"])
            assert s["evidence"] and s["check_with_agronomist"]


def test_alternatives_use_different_logics_and_crop_sets():
    r = plan_rotations(ctx(), A)
    logics = [r["details"][s["id"]]["logic"] for s in r["strategies"][1:]]
    assert len(set(logics)) == len(logics) == 3
    sets = [frozenset(c["crop"] for c in s["sequence"] if c["season"] == "main") for s in r["strategies"][1:]]
    assert len(set(sets)) == 3
    assert "cover" in logics                                                  # the cover idea is always on offer in the corn belt


def test_n_strategies_and_language():
    assert len(plan_rotations(ctx(), A, n_strategies=2)["strategies"]) == 3
    en = plan_rotations(ctx(), A, lang="en")
    assert en["strategies"][0]["name"].startswith("Current: Corn") and "cover" in " ".join(s["name"] for s in en["strategies"])


def test_priorities_change_the_scores():
    erosion = plan_rotations(ctx(), A, priorities={"water": 0, "soil_health": 0, "nitrogen": 0, "erosion": 1, "income": 0})
    income = plan_rotations(ctx(), A, priorities={"water": 0, "soil_health": 0, "nitrogen": 0, "erosion": 0, "income": 1})
    cover_e = next(s for s in erosion["strategies"] if erosion["details"][s["id"]]["logic"] == "cover")
    cover_i = next(s for s in income["strategies"] if income["details"][s["id"]]["logic"] == "cover")
    assert cover_e["delta_vs_current"]["overall"] > cover_i["delta_vs_current"]["overall"]   # cover helps erosion, costs income


def test_cover_slots_follow_the_rules():
    r = plan_rotations(ctx(), A)
    for s in r["strategies"]:
        mains = [c["crop"] for c in s["sequence"] if c["season"] == "main"]
        for c in s["sequence"]:
            if c["season"] == "cover":
                assert mains[c["year"] - 1] in ("corn", "soybean", "sorghum")             # autumn harvest
                assert mains[c["year"] % len(mains)] not in ("winter_wheat", "alfalfa")   # not before crops sown at the same time
    # rye blocked by acid soil -> no cover anywhere, and the data gap says why
    acid = plan_rotations(ctx(soil={**SOIL, "ph_h2o": 4.2}), A)
    assert all(c["season"] != "cover" for s in acid["strategies"] for c in s["sequence"])
    assert any("покривна" in g.lower() for g in acid["strategies"][0]["data_gaps"])


def test_blocked_crops_never_appear():
    r = plan_rotations(ctx(soil={**SOIL, "ph_h2o": 5.2}), A)                 # alfalfa is blocked below pH 5.5
    assert all(c["crop"] != "alfalfa" for s in r["strategies"][1:] for c in s["sequence"])


def test_irrigation_and_livestock_inputs():
    dry = ctx(precip_annual=520.0)
    base = plan_rotations(dry, A)["strategies"][0]["scores"]["water"]
    irr = plan_rotations(dry, A, farmer_input={"irrigated": True})["strategies"][0]["scores"]["water"]
    assert irr > base
    cattle = plan_rotations(ctx(), A, farmer_input={"has_livestock": True, "irrigated": False})
    no_cattle = plan_rotations(ctx(), A, farmer_input={"has_livestock": False, "irrigated": False})
    inc = lambda r: next((s["scores"]["income"] for s in r["strategies"] if r["details"][s["id"]]["logic"] == "perennial"), None)
    if inc(cattle) is not None and inc(no_cattle) is not None:
        assert inc(cattle) > inc(no_cattle)


@pytest.mark.skipif(not (ROOT / "data/features/climate_season.parquet").exists(), reason="needs data/ (not in git)")
def test_scenario_recomputes_climate_and_scores():
    from ml_service.field_context import load_field_context
    fid = "191825002125636"
    base, hot = load_field_context(fid, A), load_field_context(fid, A, scenario=(3.0, -20.0))
    assert hot.climate_norm["gdd_grow"] > base.climate_norm["gdd_grow"] + 250 and hot.climate_norm["precip_grow"] < base.climate_norm["precip_grow"]
    assert sum(hot.et0_monthly) > sum(base.et0_monthly) and hot.precip_annual == pytest.approx(0.8 * base.precip_annual, rel=1e-3)
    assert hot.winter_tmin_c > base.winter_tmin_c
    rb, rh = plan_rotations(base, A), plan_rotations(hot, A)
    assert rh["strategies"][0]["scores"]["water"] < rb["strategies"][0]["scores"]["water"]
    assert rh["strategies"][0]["metrics"]["water_use_mm_yr"] > rb["strategies"][0]["metrics"]["water_use_mm_yr"]
    assert rh["scenario"] == {"temp_delta_c": 3.0, "precip_change_pct": -20.0}
    zero = load_field_context(fid, A, scenario=(0.0, 0.0))
    assert zero.climate_norm == base.climate_norm


@pytest.mark.skipif(not (ROOT / "data/features/climate_season.parquet").exists(), reason="needs data/ (not in git)")
def test_zero_shift_recompute_equals_stored_tables():
    from ml_service import season_climate as sc
    from ml_service.field_context import CLIMATE_COLS, load_field_context
    fid = "311825007895558"
    base = load_field_context(fid, A)
    cell = pd.read_parquet(ROOT / "data/features/field_cells.parquet").set_index("field_id").loc[fid]
    n = sc.normals(sc.load_daily(str(ROOT / f"data/features/power_cache/{cell['cell']}.json"), float(cell["cell_lat"])))
    for c in CLIMATE_COLS:
        assert n["climate_norm"][c] == pytest.approx(base.climate_norm[c], abs=2e-3)
    assert n["winter_tmin_c"] == pytest.approx(base.winter_tmin_c, abs=1e-2)


# ---------------------------------------------------------------- stress rule (synthetic NDVI)

PEAK = {"corn": 7.5, "soybean": 8.0, "sorghum": 8.5}


def synthetic_ndvi(n_fields=120, last_year=2025, stressed=(), drop=0.35, seed=1):
    """monthly NDVI of corn fields in one state: a bell curve peaking in Jul-Aug plus noise; `stressed` fields lose `drop` in last_year."""
    rng = np.random.default_rng(seed)
    ids = [f"f{i:03d}" for i in range(n_fields)]
    rows = []
    for fid in ids:
        base = 0.85 + rng.normal(0, 0.03)
        for year in (last_year - 1, last_year):
            for month in range(4, 11):
                v = 0.15 + (base - 0.15) * np.exp(-((month - 7.5) ** 2) / (2 * 1.2 ** 2)) + rng.normal(0, 0.015)
                if fid in stressed and year == last_year:
                    v *= 1 - drop
                rows.append((fid, year, month, v, 3))
    ndvi = pd.DataFrame(rows, columns=["field_id", "year", "month", "ndvi_mean", "n_obs"])
    crops = pd.DataFrame([(f, y, "corn") for f in ids for y in (last_year - 1, last_year)], columns=["field_id", "year", "crop"])
    return ndvi, crops, pd.Series("IA", index=ids), ids


def test_peak_months_are_found_in_the_data():
    ndvi, crops, _, _ = synthetic_ndvi()
    assert set(peak_months(ndvi, crops, "corn", default=[5])) <= {7, 8} and len(peak_months(ndvi, crops, "corn", default=[5])) >= 1
    assert peak_months(ndvi.head(5), crops, "corn", default=[5]) == [5]          # too little data: the default months


def test_stress_detected_for_the_weak_field_only():
    ndvi, crops, state, ids = synthetic_ndvi(stressed={"f007"})
    sig = compute_stress(ndvi, crops, state, "f007", 2025, "corn", CFG["stress"])
    assert sig.active and sig.z < -1.5 and sig.intensity >= 0.5 and 30 < sig.pct_below < 40 and sig.n_neighbors == len(ids) - 1
    flags = [compute_stress(ndvi, crops, state, f, 2025, "corn", CFG["stress"]).active for f in ids if f != "f007"]
    assert sum(flags) <= 0.08 * len(flags)                                          # a normal field is almost never flagged


def test_stress_is_off_without_data_or_neighbours():
    ndvi, crops, state, _ = synthetic_ndvi(n_fields=6, stressed={"f001"})
    assert not compute_stress(ndvi, crops, state, "f001", 2025, "corn", CFG["stress"]).active          # < 10 neighbours
    assert not compute_stress(None, crops, state, "f001", 2025, "corn", CFG["stress"]).active           # no file
    assert not compute_stress(ndvi, crops, state, "f001", 2025, "other", CFG["stress"]).active          # not a candidate crop


def test_stress_multipliers_and_plan():
    ndvi, crops, state, _ = synthetic_ndvi(stressed={"f007"})
    sig = compute_stress(ndvi, crops, state, "f007", 2025, "corn", CFG["stress"])
    m = stress_multipliers(sig, A.candidates, A.transition["families"], CFG["stress"], "uk")
    assert m["corn"][0][0] < m["sorghum"][0][0] < 1 < m["soybean"][0][0]            # repeat < same family < 1 < legume
    assert "нижче за сусідів" in m["corn"][0][1]
    assert stress_multipliers(StressSignal(), A.candidates, A.transition["families"], CFG["stress"], "uk") == {}

    history = hist(["soybean", "corn"] * 4)                                          # corn last year (2025)
    base = plan_rotations(ctx(history), A)
    weak = plan_rotations(ctx(history), A, stress=sig)
    assert weak["stress"]["active"] and weak["stress"]["pct_below"] == sig.pct_below
    assert any("NDVI" in e["text"] and e["source_ids"] == ["landsat_ndvi"] for s in weak["strategies"][1:] for e in s["evidence"])
    cover = lambda r: next(s for s in r["strategies"] if r["details"][s["id"]]["logic"] == "cover")
    assert cover(weak)["scores"]["soil_health"] > cover(base)["scores"]["soil_health"]          # cover bonus
    assert weak["details"]["current"]["fit"] <= base["details"]["current"]["fit"]               # repeating corn fits worse


def test_stress_file_is_optional():
    from ml_service.stress import load_ndvi_monthly
    assert load_ndvi_monthly("/nonexistent") is None
