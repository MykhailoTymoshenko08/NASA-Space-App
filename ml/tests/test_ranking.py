"""tests for the crop ranking (rules, transitions, suitability, top-3, irrigation, serving parity)."""
import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml_service import rules as rules_mod
from ml_service.ranking import FieldContext, build_feature_row, load_assets, pick_top3, rank_crops, transition_multiplier, trapezoid

ROOT = Path(__file__).resolve().parent.parent
A = load_assets()

CLIMATE = dict(gdd_grow=1850.0, tmean_grow=19.5, tmax_summer=29.5, heat_days_32=14.0, heat_days_35=4.0, precip_grow=580.0,
               precip_spring=290.0, precip_summer=290.0, et0_grow=800.0, water_balance_grow=-220.0, max_dry_spell=11.0,
               extreme_rain_days_spring=2.0, extreme_rain_days_year=5.0, last_spring_frost_doy=112.0,
               first_fall_frost_doy=295.0, frost_free_days=183.0, srad_grow=20.5, rh_summer=68.0)
SOIL = dict(clay_pct=27.0, sand_pct=12.0, om_pct=3.5, soc_pct=2.0, ph_h2o=6.5, ec_ds_m=0.3, awc_cm_cm=0.2, kw_factor=0.3,
            hydgrp="C", drainage_class="Somewhat poorly drained", texture_class="Silt loam")


def ctx(**kw) -> FieldContext:
    base = dict(field_id="t1", state="IA", lat=41.9, lon=-93.6, prev_crops=["soybean", "corn"], soil=dict(SOIL),
                slope_pct=2.0, climate_norm=dict(CLIMATE), climate_lag1=dict(CLIMATE), winter_tmin_c=-24.0)
    base.update(kw)
    return FieldContext(**base)


def crop(r, slug):
    return next(c for c in r["crops"] if c["crop"] == slug)


# ---------------------------------------------------------------- building blocks

def test_feature_row_preserves_training_schema_and_numeric_coercion():
    field = ctx(
        prev_crops=["unknown", "barley"],
        soil={**SOIL, "clay_pct": "27.5", "sand_pct": None, "om_pct": np.nan,
              "soc_pct": "not a number", "hydgrp": "unlisted", "texture_class": None},
        slope_ssurgo="3.5", twi=None,
        climate_norm={**CLIMATE, "gdd_grow": "1900", "tmean_grow": None},
        climate_lag1={**CLIMATE, "gdd_grow": np.nan},
    )
    row = build_feature_row(field, A)
    assert list(row.columns) == A.features
    assert list(row.index) == [0]
    for name in A.features:
        if name in A.levels:
            assert row[name].dtype == pd.CategoricalDtype(categories=A.levels[name])
        else:
            assert row[name].dtype == np.dtype("float64")
    assert row.loc[0, "state_fips"] == "19"
    assert pd.isna(row.loc[0, "prev_crop_1"])
    assert row.loc[0, "prev_crop_2"] == "other"
    assert row.loc[0, "clay_pct"] == 27.5
    assert row.loc[0, "slope_pct"] == 3.5
    assert row.loc[0, "norm_gdd_grow"] == 1900.0
    for name in ("sand_pct", "om_pct", "soc_pct", "hydgrp", "texture_class",
                 "norm_tmean_grow", "lag1_gdd_grow"):
        assert pd.isna(row.loc[0, name]), name


def test_trapezoid_shape():
    b = {k: {"value": v} for k, v in zip(("hard_min", "opt_min", "opt_max", "hard_max"), (5.0, 6.0, 7.0, 8.0))}
    assert trapezoid(6.5, b) == 1.0
    assert trapezoid(5.5, b) == pytest.approx(0.5) and trapezoid(7.5, b) == pytest.approx(0.5)
    assert trapezoid(5.0, b) == 0.0 and trapezoid(8.5, b) == 0.0
    assert trapezoid(None, b) is None and trapezoid(float("nan"), b) is None
    open_low = {k: {"value": v} for k, v in zip(("hard_min", "opt_min", "opt_max", "hard_max"), (None, None, 4.0, 10.0))}
    assert trapezoid(-3.0, open_low) == 1.0 and trapezoid(7.0, open_low) == pytest.approx(0.5)


def test_transition_multipliers():
    beta = A.transition["beta"]
    assert beta == 0.5
    m = lambda prev, c: transition_multiplier(prev, c, A)[0]
    assert m("soybean", "soybean") == pytest.approx(0.1 ** beta) and m("corn", "corn") == pytest.approx(0.1 ** beta)  # monoculture
    assert m("soybean", "corn") == pytest.approx(1.5 ** beta) and m("alfalfa", "winter_wheat") == pytest.approx(1.5 ** beta)  # after a legume
    assert m("corn", "winter_wheat") == pytest.approx(0.5 ** beta) and m("soybean", "alfalfa") == pytest.approx(0.5 ** beta)  # same family
    assert m("corn", "soybean") == 1.0                                           # neutral
    assert m("other", "corn") == 1.0 and m("unknown", "soybean") == 1.0          # fallow / no data
    assert m("alfalfa", "alfalfa") == 1.0                                        # a perennial stand goes on


def test_rules_block_and_ramp():
    ev = lambda slug, **v: rules_mod.evaluate_crop(slug, v, A.rules, {"monoculture", "legume_before_cereal"})
    fired, _ = ev("alfalfa", **{"soil.ph": 5.3})
    assert any(r.rule_id == "acid_soil_alfalfa" and r.kind == "block" for r in fired)
    assert not any(r.kind == "block" for r in ev("alfalfa", **{"soil.ph": 6.5})[0])
    fired, _ = ev("corn", **{"climate.gdd_grow": 1300.0})                       # value_ref: crop.gdd_to_maturity
    assert any(r.rule_id == "gdd_shortfall" for r in fired)
    assert not any(r.rule_id == "gdd_shortfall" for r in ev("corn", **{"climate.gdd_grow": 1500.0})[0])
    w = {r.rule_id: r for r in ev("winter_wheat", **{"climate.winter_tmin_c": -25.0})[0]}
    assert w["winterkill_risk_winter_wheat"].multiplier == pytest.approx(1 - 0.35 * 0.5)   # halfway on the ramp
    assert not ev("winter_wheat", **{"climate.winter_tmin_c": -15.0})[0]
    assert not any(r.rule_id == "winterkill_risk_winter_wheat" for r in ev("corn", **{"climate.winter_tmin_c": -30.0})[0])
    assert "chronic_summer_moisture_deficit_corn" in ev("corn", **{})[1]            # no SMAP: reported, not guessed


# ---------------------------------------------------------------- ranking

def test_ranking_structure_and_order():
    r = rank_crops(ctx(), A)
    assert len(r["crops"]) == 8
    scores = [c["score"] for c in r["crops"]]
    assert scores == sorted(scores, reverse=True)
    assert r["crops"][0]["crop"] == "corn" and r["crops"][0]["relative"] == 100.0   # corn after soybean in Iowa
    assert sum(r["model_probs"].values()) == pytest.approx(1.0, abs=1e-3)
    for c in r["crops"]:
        assert set(c["parts"]) == {"model_prob", "model_prob_source", "transition", "suitability", "rules", "water", "water_ratio"}
        assert len(c["main_factors"]) <= 3
        assert c["model_class"] == (c["parts"]["model_prob_source"] == "model")
    for slug in ("oats", "barley", "cereal_rye"):                                   # rules-only: neutral, not the model
        assert crop(r, slug)["parts"]["model_prob_source"] == "neutral"
        assert crop(r, slug)["parts"]["model_prob"] == pytest.approx(r["neutral_model_prob"], abs=1e-4)


def test_top3_groups_roles_and_no_cover():
    r = rank_crops(ctx(), A)
    top = r["top3"]
    assert [c["rank"] for c in top] == [1, 2, 3]
    assert len({c["crop"] for c in top}) == 3
    assert top[1]["group"] != top[0]["group"]                                        # #2 is from another group
    assert all(c["crop"] != "cereal_rye" for c in top)                               # a cover crop is not a main crop
    assert top[0]["score"] == max(c["score"] for c in r["crops"])


def test_blocked_crops_have_reasons_and_leave_the_top3():
    r = rank_crops(ctx(soil={**SOIL, "ph_h2o": 5.2}), A)
    alfalfa = crop(r, "alfalfa")
    assert alfalfa["status"] == "blocked" and alfalfa["score"] == 0 and alfalfa["blocked_reasons"]
    assert all(c["crop"] != "alfalfa" for c in r["top3"])
    r_en = rank_crops(ctx(soil={**SOIL, "ph_h2o": 5.2}), A, lang="en")
    assert any("pH" in x for x in crop(r_en, "alfalfa")["blocked_reasons"])


def test_everything_blocked_gives_empty_top3_with_message():
    r = rank_crops(ctx(soil={**SOIL, "ph_h2o": 9.5, "ec_ds_m": 12.0}), A)
    assert r["top3"] == [] and all(c["status"] == "blocked" for c in r["crops"])
    assert "жорсткі фільтри" in r["data_gaps"][0]


def test_winter_wheat_penalised_in_cold_winters_only():
    cold, mild = rank_crops(ctx(winter_tmin_c=-28.0), A), rank_crops(ctx(winter_tmin_c=-16.0), A)
    assert crop(cold, "winter_wheat")["parts"]["rules"] == pytest.approx(0.65)
    assert crop(mild, "winter_wheat")["parts"]["rules"] == pytest.approx(1.0)


def test_irrigation_ignores_rainfall():
    dry_climate = {**CLIMATE, "precip_grow": 330.0}
    base, irr = rank_crops(ctx(climate_norm=dry_climate), A), rank_crops(ctx(climate_norm=dry_climate), A, irrigated=True)
    assert crop(irr, "corn")["parts"]["suitability"] > crop(base, "corn")["parts"]["suitability"]
    assert irr["irrigated"] is True and "зрошується" in irr["data_gaps"][-1]
    # a field so dry that corn is blocked by rainfall is not blocked when irrigated
    very_dry = {**CLIMATE, "precip_grow": 250.0}
    assert crop(rank_crops(ctx(climate_norm=very_dry), A), "corn")["status"] == "blocked"
    assert crop(rank_crops(ctx(climate_norm=very_dry), A, irrigated=True), "corn")["status"] == "ok"


def test_language_switch():
    uk, en = rank_crops(ctx(), A), rank_crops(ctx(), A, lang="en")
    assert crop(uk, "corn")["name"] == "Кукурудза" and crop(en, "corn")["name"] == "Corn"
    assert en["top3"][0]["role"] == "highest score"


def test_pick_top3_prefers_new_group_and_tolerance():
    def c(slug, group, score):
        return {"crop": slug, "group": group, "score": score, "status": "ok", "relative": score}
    crops = [c("corn", "cereal", 100.0), c("soybean", "legume", 50.0), c("sorghum", "cereal", 20.0),
             c("alfalfa", "other", 10.0), c("winter_wheat", "cereal", 5.0)]
    top = pick_top3(crops, A, "en")
    assert [x["crop"] for x in top] == ["corn", "soybean", "alfalfa"]                # new group beats higher tolerance of sorghum
    crops = [c("corn", "cereal", 100.0), c("soybean", "legume", 50.0), c("sorghum", "cereal", 20.0), c("winter_wheat", "cereal", 15.0)]
    assert [x["crop"] for x in pick_top3(crops, A, "en")][2] == "sorghum"            # most heat/drought tolerant of the rest


# ---------------------------------------------------------------- serving matches training (needs data/, gitignored)

@pytest.mark.skipif(not (ROOT / "data/dataset/crops_train.parquet").exists(), reason="needs data/ (not in git)")
def test_serving_features_equal_training_table():
    from ml_service.field_context import load_field_context
    d = pd.read_parquet(ROOT / "data/dataset/crops_train.parquet").sample(60, random_state=1)
    for r in d.itertuples():
        x = build_feature_row(load_field_context(r.field_id, A, target_year=r.year), A).iloc[0]
        for f in A.features:
            want, got = getattr(r, f), x[f]
            if pd.isna(want) and pd.isna(got):
                continue
            if isinstance(want, (int, float, np.number)) and not isinstance(want, bool):
                assert float(got) == pytest.approx(float(want), abs=1e-6), (r.field_id, r.year, f)
            else:
                assert str(got) == str(want), (r.field_id, r.year, f)
