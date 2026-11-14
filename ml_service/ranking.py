"""Crop ranking for one field: which crop to grow next, and why.

score = hard filters (0 = out, with the reason)
        x calibrated model probability          (rules-only crops: a neutral value instead)
        x transition previous crop -> crop       (config/transition_matrix.yaml)
        x suitability                            (geometric mean of the trapezoids, config/suitability.yaml)
        x soft rules                             (penalties / bonuses of config/crop_rules.yaml)
hard filters = rules with hard_block + suitability hard bounds.

top-3 of different groups (cereal / legume / other):
  #1 the highest score
  #2 the best crop of another group
  #3 the most heat- and drought-tolerant of what is left (a group not yet used is preferred)

If the field is irrigated, rainfall (suitability of precipitation, IMERG rules) and SMAP rules are ignored.
The rotations are built from this ranking elsewhere; this module only ranks crops.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml

from . import rules as rules_mod
from .feature_text import GROUP_LABEL, crop_name, feature_group, feature_plain

ROOT = Path(__file__).resolve().parent.parent
FIPS = {"IA": "19", "IL": "17", "KS": "20", "NE": "31"}
SKIP_RULES = {"monoculture", "legume_before_cereal"}   # the transition matrix covers these two
RESILIENT_MIN_RATIO = 0.01     # the "most heat/drought tolerant" pick must have at least 1% of the best score
WEAK_BELOW = 5.0               # relative score under 5 (of 100) is marked as a weak alternative
SUIT_FEATURES = ["ph_h2o", "clay_pct", "soc_pct", "ec_ds_m", "gdd_norm", "precip_norm", "slope_pct"]
WATER_SUIT = {"precip_norm"}   # ignored when the field is irrigated

SUIT_PLAIN = {  # feature -> (en, uk)
    "ph_h2o": ("soil pH", "кислотність ґрунту (pH)"), "clay_pct": ("clay, %", "вміст глини, %"),
    "soc_pct": ("organic carbon, %", "органічний вуглець, %"), "ec_ds_m": ("salinity (EC), dS/m", "засоленість (EC), дСм/м"),
    "gdd_norm": ("typical heat sum", "типова сума активних температур"), "precip_norm": ("typical growing-season rain, mm", "типові опади за вегетацію, мм"),
    "slope_pct": ("slope, %", "ухил, %"),
}
GROUP_NAME = {"cereal": ("cereals", "злакові"), "legume": ("legumes", "бобові"), "other": ("other (perennial forage)", "інше (багаторічні кормові)")}

T = {
    "uk": {
        "raises": "підвищує шанси", "lowers": "знижує шанси",
        "adj_transition": "{reason} (×{m:.2f})",
        "adj_rule": "{expl} (×{m:.2f})",
        "adj_suit": "{plain} = {value}: поза оптимальним діапазоном ({rng}) (×{f:.2f})",
        "block_suit": "{plain} = {value}: поза допустимим діапазоном ({rng}) для цієї культури",
        "neutral_model": "для цієї культури немає прогнозу моделі (надто мало прикладів у даних); взято нейтральне значення {p:.3f}",
        "perennial_continue": "багаторічна культура: продовження посіву не вважається монокультурою",
        "gap_unevaluated": "не перевірені правила через відсутні дані ({vars}): {ids}",
        "gap_imerg": "IMERG ще немає: опади взяті з NASA POWER",
        "irrigated_note": "поле зрошується: опади та вологість ґрунту (SMAP) не враховано",
        "nothing_fits": "жодна культура не пройшла жорсткі фільтри для цього поля (див. причини виключення)",
        "weak": "слабка альтернатива", "range_to": "до {hi}", "range_from": "від {lo}",
        "role_best": "найвищий бал", "role_other_group": "найкраща з іншої групи ({group})",
        "role_resilient": "найстійкіша до спеки й посухи", "role_fill": "наступна за балом",
        "factor_fmt": "{label}: {detail} — {verb}",
    },
    "en": {
        "raises": "raises the chance", "lowers": "lowers the chance",
        "adj_transition": "{reason} (x{m:.2f})",
        "adj_rule": "{expl} (x{m:.2f})",
        "adj_suit": "{plain} = {value}: outside the optimal range ({rng}) (x{f:.2f})",
        "block_suit": "{plain} = {value}: outside the allowed range ({rng}) for this crop",
        "neutral_model": "the model has no forecast for this crop (too few examples); a neutral value {p:.3f} is used",
        "perennial_continue": "perennial crop: continuing the stand is not monoculture",
        "gap_unevaluated": "rules not evaluated because data is missing ({vars}): {ids}",
        "gap_imerg": "IMERG is not available yet: rainfall taken from NASA POWER",
        "irrigated_note": "field is irrigated: rainfall and soil moisture (SMAP) are not counted",
        "nothing_fits": "no crop passes the hard filters for this field (see the reasons for exclusion)",
        "weak": "weak alternative", "range_to": "up to {hi}", "range_from": "from {lo}",
        "role_best": "highest score", "role_other_group": "best of another group ({group})",
        "role_resilient": "most heat- and drought-tolerant", "role_fill": "next by score",
        "factor_fmt": "{label}: {detail} - {verb}",
    },
}


# --------------------------------------------------------------------------- inputs / assets

@dataclass
class FieldContext:
    """everything the ranking needs to know about one field (what is known before sowing)."""
    field_id: str
    state: str                       # IA / IL / KS / NE
    lat: float
    lon: float
    prev_crops: list[str]            # [last year, the year before]; candidate slug, "other", or "unknown"
    soil: dict                       # clay_pct sand_pct om_pct soc_pct ph_h2o ec_ds_m awc_cm_cm kw_factor hydgrp drainage_class texture_class
    slope_pct: float | None
    climate_norm: dict               # the 18 season climate values, normal of the POWER cell
    climate_lag1: dict               # the same 18 values for last season
    winter_tmin_c: float | None = None
    twi: float | None = None
    smap_deficit_share: float | None = None
    irrigated: bool | None = None


@dataclass
class Assets:
    booster: lgb.Booster
    classes: list[str]
    features: list[str]
    levels: dict
    calibrator: dict
    candidates: dict
    rules: dict
    suitability: dict
    transition: dict
    root: Path = field(default=ROOT)


def load_assets(root: Path = ROOT) -> Assets:
    model_dir = root / "models" / "crop_model"
    fl = json.loads((model_dir / "feature_list.json").read_text())
    load_yaml = lambda name: yaml.safe_load((root / "config" / name).read_text())
    return Assets(
        booster=lgb.Booster(model_file=str(model_dir / "model.txt")),
        classes=fl["classes"], features=fl["features"], levels=fl["category_levels"],
        calibrator=json.loads((model_dir / "calibrator.json").read_text()),
        candidates=load_yaml("candidate_crops.yaml")["crops"], rules=load_yaml("crop_rules.yaml"),
        suitability=load_yaml("suitability.yaml")["crops"], transition=load_yaml("transition_matrix.yaml"), root=root,
    )


# --------------------------------------------------------------------------- model

def build_feature_row(ctx: FieldContext, a: Assets) -> pd.DataFrame:
    """one-row frame with exactly the training features, same categories as in training."""
    def model_crop(c):  # classes of the model are kept, everything else is "other" (as in the training table)
        return c if c in a.classes else ("other" if c is not None else None)

    row = {"lat": ctx.lat, "lon": ctx.lon, "state_fips": FIPS[ctx.state],
           "prev_crop_1": model_crop(ctx.prev_crops[0]) if ctx.prev_crops[0] != "unknown" else None,
           "prev_crop_2": model_crop(ctx.prev_crops[1]) if ctx.prev_crops[1] != "unknown" else None,
           "slope_pct": ctx.slope_pct, "twi": ctx.twi, **ctx.soil}
    row.update({f"norm_{k}": v for k, v in ctx.climate_norm.items()})
    row.update({f"lag1_{k}": v for k, v in ctx.climate_lag1.items()})
    x = pd.DataFrame([{f: row.get(f, np.nan) for f in a.features}])
    for c, lv in a.levels.items():
        x[c] = pd.Categorical(x[c], categories=lv)
    return x


def calibrate(p: np.ndarray, cal: dict) -> np.ndarray:
    if cal["method"] == "temperature":
        q = np.clip(p, 1e-12, 1.0) ** (1.0 / cal["temperature"])
        return q / q.sum(axis=1, keepdims=True)
    out = np.column_stack([np.interp(p[:, c], cv["x"], cv["y"]) for c, cv in enumerate(cal["curves"])])
    out = np.clip(out, 1e-6, 1.0)
    return out / out.sum(axis=1, keepdims=True)


def model_forecast(ctx: FieldContext, a: Assets):
    """calibrated probabilities per class + the SHAP contributions of every feature per class."""
    x = build_feature_row(ctx, a)
    raw = a.booster.predict(x)
    probs = calibrate(np.asarray(raw), a.calibrator)[0]
    k, f = len(a.classes), len(a.features)
    contrib = a.booster.predict(x, pred_contrib=True).reshape(k, f + 1)[:, :f]
    return x, probs, contrib


def shap_factors(x: pd.DataFrame, contrib_row: np.ndarray, features: list[str], lang: str, top: int = 3) -> list[dict]:
    """top reasons for one crop: contributions are added up inside readable groups (last year's crop, soil, ...)."""
    t = T[lang]
    groups: dict[str, list[int]] = {}
    for j, name in enumerate(features):
        groups.setdefault(feature_group(name), []).append(j)
    out = []
    for g, idx in groups.items():
        total = float(contrib_row[idx].sum())
        lead = idx[int(np.abs(contrib_row[idx]).argmax())]
        name, val = features[lead], x.iloc[0][features[lead]]
        if g in ("prev1", "prev2"):
            detail = crop_name(str(val), lang) if pd.notna(val) else ("невідомо" if lang == "uk" else "unknown")
        else:
            shown = f"{val:.1f}" if isinstance(val, (int, float, np.floating)) and pd.notna(val) else str(val)
            detail = f"{feature_plain(name, lang)} = {shown}"
        out.append({"group": g, "effect": total, "text": t["factor_fmt"].format(
            label=GROUP_LABEL[g][1 if lang == "uk" else 0], detail=detail, verb=t["raises"] if total > 0 else t["lowers"])})
    out.sort(key=lambda r: -abs(r["effect"]))
    return [{"text": r["text"], "effect": round(r["effect"], 3), "direction": "+" if r["effect"] > 0 else "-"} for r in out[:top]]


# --------------------------------------------------------------------------- suitability / transitions

def trapezoid(x, b: dict) -> float | None:
    """0 outside the hard bounds (crop blocked), 1 on the plateau, linear in between. None bound = open side."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    hmin, omin, omax, hmax = (b[k]["value"] for k in ("hard_min", "opt_min", "opt_max", "hard_max"))
    if hmin is not None and x <= hmin:
        return 0.0
    if hmax is not None and x >= hmax:
        return 0.0
    if omin is not None and hmin is not None and x < omin:
        return (x - hmin) / (omin - hmin)
    if omax is not None and hmax is not None and x > omax:
        return (hmax - x) / (hmax - omax)
    return 1.0


def suitability_values(ctx: FieldContext) -> dict:
    return {"ph_h2o": ctx.soil.get("ph_h2o"), "clay_pct": ctx.soil.get("clay_pct"), "soc_pct": ctx.soil.get("soc_pct"),
            "ec_ds_m": ctx.soil.get("ec_ds_m"), "gdd_norm": ctx.climate_norm.get("gdd_grow"),
            "precip_norm": ctx.climate_norm.get("precip_grow"), "slope_pct": ctx.slope_pct}


def fmt_range(lo, hi, lang: str, digits: int = 2) -> str:
    """"5.5-7.5", or "up to 4.4" / "from 0.9" when a side is open"""
    t = T[lang]
    r = lambda v: round(float(v), digits)
    if lo is None and hi is None:
        return "—"
    if lo is None:
        return t["range_to"].format(hi=r(hi))
    if hi is None:
        return t["range_from"].format(lo=r(lo))
    return f"{r(lo)}–{r(hi)}"


def transition_multiplier(prev: str, crop: str, a: Assets) -> tuple[float, str | None]:
    """(effective multiplier, reason). effective = matrix value ** beta (the model already sees the previous crops)."""
    raw, why = _transition_raw(prev, crop, a)
    return raw ** a.transition.get("beta", 1.0), why


def _transition_raw(prev: str, crop: str, a: Assets) -> tuple[float, str | None]:
    cfg, cand = a.transition, a.candidates
    m = cfg["multipliers"]
    if prev not in cand:                     # fallow, pasture, unknown: nothing to say
        return m["neutral"], None
    if prev == crop:
        if a.rules["crops"][crop]["type"] == "perennial":
            return m["neutral"], "perennial_continue"
        return m["same_crop"], "same_crop"
    if cand[prev]["legume"] and not cand[crop]["legume"]:
        return m["after_legume"], "after_legume"
    fam = {c: f for f, members in cfg["families"].items() for c in members}
    if fam.get(prev) == fam.get(crop):
        return m["same_family"], "same_family"
    return m["neutral"], None


# --------------------------------------------------------------------------- the ranking

def rank_crops(ctx: FieldContext, a: Assets, lang: str = "uk", irrigated: bool | None = None) -> dict:
    t = T[lang]
    irrigated = ctx.irrigated if irrigated is None else irrigated
    li = 1 if lang == "uk" else 0

    x, probs, contrib = model_forecast(ctx, a)
    model_probs = dict(zip(a.classes, probs))
    # a crop without a model forecast (rules-only) is treated as likely as the field's LEAST likely modelled crop:
    # the data says these crops are rare, so rules alone can lift them only when the modelled crops are out
    neutral = float(np.min(probs))

    variables = {
        "soil.clay_pct": ctx.soil.get("clay_pct"), "soil.ph": ctx.soil.get("ph_h2o"), "soil.ec_ds_m": ctx.soil.get("ec_ds_m"),
        "soil.soc_pct": ctx.soil.get("soc_pct"), "terrain.slope_pct": ctx.slope_pct, "terrain.twi": ctx.twi,
        "climate.gdd_grow": ctx.climate_norm.get("gdd_grow"), "climate.winter_tmin_c": ctx.winter_tmin_c,
        "smap.jul_aug_deficit_years_share": ctx.smap_deficit_share,
        "imerg.precip_grow_mm": ctx.climate_norm.get("precip_grow"),   # IMERG not available yet: POWER normal
    }
    skip_prefix = ("smap.", "imerg.") if irrigated else ()
    suit_values = suitability_values(ctx)

    crops_out, unevaluated = [], {}
    for slug in a.candidates:
        blocked, adjustments = [], []
        in_model = slug in a.classes

        # model probability, or the neutral value for rules-only crops
        prob = float(model_probs[slug]) if in_model else neutral
        if not in_model:
            adjustments.append({"text": t["neutral_model"].format(p=neutral), "multiplier": 1.0})

        # previous crop -> crop
        prev = ctx.prev_crops[0]
        tm, why = transition_multiplier(prev, slug, a)
        if why:
            reason = t["perennial_continue"] if why == "perennial_continue" else a.transition["reasons"][why]["uk" if lang == "uk" else "en"]
            adjustments.append({"text": t["adj_transition"].format(reason=reason, m=tm), "multiplier": tm})

        # suitability trapezoids
        suit_factors = []
        for name in SUIT_FEATURES:
            if irrigated and name in WATER_SUIT:
                continue
            b = a.suitability[slug][name]
            v = suit_values[name]
            f = trapezoid(v, b)
            if f is None:
                continue
            lo, hi = b["hard_min"]["value"], b["hard_max"]["value"]
            plain = SUIT_PLAIN[name][li]
            if f == 0.0:
                blocked.append(t["block_suit"].format(plain=plain, value=round(v, 2), rng=fmt_range(lo, hi, lang)))
            else:
                suit_factors.append(f)
                if f < 0.98:
                    omin, omax = b["opt_min"]["value"], b["opt_max"]["value"]
                    adjustments.append({"text": t["adj_suit"].format(
                        plain=plain, value=round(v, 2), rng=fmt_range(omin, omax, lang), f=f), "multiplier": f})
        suit = float(np.exp(np.mean(np.log(suit_factors)))) if suit_factors else 1.0

        # agronomic rules
        fired, unknown = rules_mod.evaluate_crop(slug, variables, a.rules, SKIP_RULES, skip_prefix)
        rules_mult = 1.0
        for r in fired:
            if r.kind == "block":
                blocked.append(r.explanation["uk" if lang == "uk" else "en"])
            else:
                rules_mult *= r.multiplier
                adjustments.append({"text": t["adj_rule"].format(expl=r.explanation["uk" if lang == "uk" else "en"], m=r.multiplier),
                                    "multiplier": r.multiplier})
        for rid in unknown:
            unevaluated.setdefault(rid, set()).add(slug)

        score = 0.0 if blocked else prob * tm * suit * rules_mult

        # main factors: SHAP for model crops, the biggest adjustments for rules-only crops
        if in_model:
            factors = shap_factors(x, contrib[a.classes.index(slug)], a.features, lang)
        else:
            ranked_adj = sorted((ad for ad in adjustments if ad["multiplier"] != 1.0), key=lambda ad: -abs(np.log(ad["multiplier"])))
            factors = [{"text": ad["text"], "effect": round(float(np.log(ad["multiplier"])), 3),
                        "direction": "+" if ad["multiplier"] > 1 else "-"} for ad in ranked_adj[:3]]

        crops_out.append({
            "crop": slug, "name": crop_name(slug, lang), "group": a.candidates[slug]["group"],
            "model_class": in_model, "status": "blocked" if blocked else "ok", "score": score,
            "parts": {"model_prob": round(prob, 4), "model_prob_source": "model" if in_model else "neutral",
                      "transition": tm, "suitability": round(suit, 3), "rules": round(rules_mult, 3)},
            "blocked_reasons": blocked, "adjustments": adjustments, "main_factors": factors,
        })

    best = max((c["score"] for c in crops_out), default=0.0)
    for c in crops_out:
        c["relative"] = round(100 * c["score"] / best, 1) if best > 0 else 0.0
        c["weak"] = c["status"] == "ok" and c["relative"] < WEAK_BELOW
        c["score"] = round(c["score"], 5)
    crops_out.sort(key=lambda c: (-c["score"], c["crop"]))

    gaps = []
    if unevaluated:
        needs = sorted({v.split(".")[0] for rid in unevaluated for rule in a.rules["rules"] if rule["id"] == rid
                        for v in rules_mod.rule_variables(rule) if variables.get(v) is None})
        gaps.append(t["gap_unevaluated"].format(vars=", ".join(needs), ids=", ".join(sorted(unevaluated))))
    if not irrigated:
        gaps.append(t["gap_imerg"])
    else:
        gaps.append(t["irrigated_note"])

    top3 = pick_top3(crops_out, a, lang)
    if not top3:
        gaps.insert(0, t["nothing_fits"])
    return {"field_id": ctx.field_id, "language": lang, "irrigated": irrigated, "model_probs": {k: round(float(v), 4) for k, v in model_probs.items()},
            "neutral_model_prob": round(neutral, 4), "crops": crops_out, "top3": top3, "data_gaps": gaps}


def pick_top3(crops: list[dict], a: Assets, lang: str) -> list[dict]:
    """#1 best score; #2 best of another group; #3 most heat/drought tolerant of the rest (a new group preferred).
    cover crops are never offered as a main crop. always returns up to 3; weak picks are flagged."""
    t = T[lang]
    li = 1 if lang == "uk" else 0
    ok = [c for c in crops if c["status"] == "ok" and c["score"] > 0 and a.candidates[c["crop"]].get("role") != "cover"]
    if not ok:
        return []
    best = ok[0]["score"]
    chosen = [dict(ok[0], role=t["role_best"])]

    other = [c for c in ok if c["group"] != chosen[0]["group"]]
    if other:
        chosen.append(dict(other[0], role=t["role_other_group"].format(group=GROUP_NAME[other[0]["group"]][li])))
    elif len(ok) > 1:
        chosen.append(dict(ok[1], role=t["role_fill"]))

    used = {c["crop"] for c in chosen}
    left = [c for c in ok if c["crop"] not in used]
    strong = [c for c in left if c["score"] >= RESILIENT_MIN_RATIO * best]
    new_group = [c for c in strong if c["group"] not in {x["group"] for x in chosen}]
    pool = new_group or strong
    tol = lambda c: a.candidates[c["crop"]]["heat_drought_tolerance"]
    if pool:
        chosen.append(dict(max(pool, key=lambda c: (tol(c), c["score"])), role=t["role_resilient"]))
    elif left:   # nothing strong enough is tolerant: take the next by score
        chosen.append(dict(left[0], role=t["role_fill"]))
    for i, c in enumerate(chosen, 1):
        c["rank"] = i
    return chosen
