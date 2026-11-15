"""The real /ml/v1/analyze (docs/api_contract.md): features -> crop ranking -> rotation planner -> response.

  detected_rotation        the current rotation read from the CSB history (or stated by the farmer)
  vulnerability_timeline   12 months from the climate normal; bare soil from NDVI when there is NDVI, else the crop calendar
  summary                  headline and three key numbers from the real data
  strategies               the current rotation + n alternatives (ml_service/rotations.py)
  crop_suitability         NEW: the crop ranking (ml_service/ranking.py): score, rank, blocked, reasons, main factors
  sources                  only the ones really used
  status "partial" when NDVI or SMAP is missing (or the soil is organic); a missing TWI is only a warning
"""
from __future__ import annotations

import math
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import agro, features, precomputed
from .cdl import components
from .feature_text import crop_name
from .errors import invalid_input
from .ranking import ROOT, Assets, load_assets, rank_crops
from .rotations import load_settings, plan_rotations
from .stress import StressSignal, compute_stress, load_ndvi_monthly
from .texts import DISCLAIMER, MONTHS, SOURCES

MODEL_VERSION_REAL = "0.2.0"
DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
BARE_NDVI = 0.2               # NDVI under this means bare soil
FLAGS = {"bare": 0.7, "drought": 0.35, "heat": 0.3, "frost": 0.5, "extreme_rain": 0.3, "waterlogging": 0.25}
ALWAYS_USED = ["csb", "power", "ssurgo"]

RT = {
    "uk": {
        "headline": "Поле голе ~{bare} днів на рік{water}.", "water_short": ", а в {months} вологи бракує (випаровування більше за опади)",
        "water_ok": ", вологи здебільшого достатньо",
        "kn_bare": "Днів з голим ґрунтом на рік", "kn_deficit": "Дефіцит води в липні–серпні (ET0 − опади)", "kn_heat": "Днів > 32°C (середнє)",
        "u_days": "дн.", "u_mm": "мм",
        "w_ndvi": "Немає NDVI від Landsat: голий ґрунт у таймлайні взято з календаря культур, правило стресу минулого сезону вимкнене",
        "w_smap": "Немає даних SMAP: правила про вологу ґрунту не перевірені", "w_twi": "Немає TWI: правила про вологі пониження не перевірені",
        "w_dem": "Немає DEM NASADEM: ухил береться зі SSURGO",
        "w_organic": "organic soil (органіка понад 20%): оцінки для торфових ґрунтів ненадійні",
        "w_rotation": "Чіткого повторюваного циклу в історії культур не знайдено, поточна сівозміна визначена приблизно",
        "w_few": "Можливо лише {have} із {want} запитаних альтернатив",
        "excluded": "Культуру виключив фермер (farmer_input.excluded_crops)",
        "rotation_unknown_crop": "У farmer_input.current_rotation невідома або покривна культура: {crop}",
        "src_precomputed": "Ознаки поля взято з попередньо порахованих даних", "src_on_the_fly": "Ознаки поля пораховано на льоту (SDA + POWER)",
        "x_blocked": "Виключено: {reason}",
        "x_cover": "Покривна культура: не пропонується як основна, її місце в сівозміні дивіться в стратегіях.",
        "x_rules_only": "Модель цю культуру не оцінює (у регіоні замало прикладів); ураховано лише правила (придатність {fit}).",
        "x_top": "Найкращий вибір на наступний рік: підходить полю (придатність {fit}) і добре йде після «{prev}» ({share}% рекомендацій).",
        "x_top_weak": "Найчастіший вибір у регіоні після «{prev}» ({share}% рекомендацій), але полю він підходить слабко (придатність {fit}).",
        "x_water": " Води бракує: опади й запас ґрунту покривають лише {pct}% потреби культури. Якщо поле зрошується, вкажіть irrigated=true: рекомендація зміниться.",
        "x_same_crop": "Підходить полю (придатність {fit}), але торік уже була {prev}: повтор тієї ж культури знижує шанс до {share}%.",
        "x_same_family": "Підходить полю (придатність {fit}), але торік була {prev} тієї ж родини: спільні хвороби та шкідники, тож лише {share}%.",
        "x_other_prev": "Підходить полю (придатність {fit}), але після «{prev}» вдаліша {top} ({top_share}% проти {share}%).",
        "x_low_fit": "Слабко підходить цьому полю (придатність {fit}): у регіоні таке поле засівають нею рідко.",
        "x_prev_helps": "Полю підходить помірно (придатність {fit}), але після «{prev}» її в регіоні часто сіють ({share}% рекомендацій).",
    },
    "en": {
        "headline": "Field is bare ~{bare} days/year{water}.", "water_short": " and short on moisture in {months} (evaporation exceeds rain)",
        "water_ok": " and moisture is adequate in most months",
        "kn_bare": "Bare soil days / year", "kn_deficit": "Jul–Aug water deficit (ET0 − rain)", "kn_heat": "Days > 32°C (avg)",
        "u_days": "days", "u_mm": "mm",
        "w_ndvi": "No Landsat NDVI: bare soil in the timeline comes from the crop calendar and the last-season stress rule is off",
        "w_smap": "No SMAP data: soil-moisture rules were not evaluated", "w_twi": "No TWI: low-lying wetness rules were not evaluated",
        "w_dem": "No NASADEM DEM: slope comes from SSURGO",
        "w_organic": "organic soil (organic matter over 20%): estimates for peat / muck soils are unreliable",
        "w_rotation": "No stable repeating cycle in the crop history; the current rotation is approximate",
        "w_few": "Only {have} of {want} requested alternatives are possible",
        "excluded": "Excluded by the farmer (farmer_input.excluded_crops)",
        "rotation_unknown_crop": "farmer_input.current_rotation has an unknown or cover crop: {crop}",
        "src_precomputed": "Field features come from precomputed data", "src_on_the_fly": "Field features were computed on the fly (SDA + POWER)",
        "x_blocked": "Excluded: {reason}",
        "x_cover": "A cover crop: not offered as a main crop, see the strategies for where it fits in the rotation.",
        "x_rules_only": "The model does not score this crop (too few examples in the region); only the rules count (fit {fit}).",
        "x_top": "Best choice for next year: it suits the field (fit {fit}) and follows '{prev}' well ({share}% of the advice).",
        "x_top_weak": "The most usual choice in the region after '{prev}' ({share}% of the advice), but it suits this field poorly (fit {fit}).",
        "x_water": " Short of water: rain and soil moisture cover only {pct}% of the crop's need. If the field is irrigated, set irrigated=true — the recommendation will change.",
        "x_same_crop": "Suits the field (fit {fit}), but last year was already {prev}: repeating the same crop cuts its chance to {share}%.",
        "x_same_family": "Suits the field (fit {fit}), but last year was {prev} of the same plant family: shared diseases and pests, so only {share}%.",
        "x_other_prev": "Suits the field (fit {fit}), but after '{prev}' {top} works better ({top_share}% vs {share}%).",
        "x_low_fit": "Suits this field poorly (fit {fit}): fields like this are rarely sown with it in the region.",
        "x_prev_helps": "Suits the field only moderately (fit {fit}), but after '{prev}' it is often sown in the region ({share}% of the advice).",
    },
}


# --------------------------------------------------------------------------- assets (loaded once)

@lru_cache(maxsize=1)
def assets() -> Assets:
    return load_assets()


@lru_cache(maxsize=1)
def settings() -> dict:
    return load_settings()


def warm_up() -> None:
    """load the model and the tables before the first request"""
    assets()
    settings()
    precomputed.count()
    try:
        from .field_context import _tables
        _tables(str(features.DATA_DIR))
    except OSError:
        pass


def lina_dir() -> Path:
    return Path(os.environ.get("ML_LINA_DIR", ROOT / "data" / "lina"))


@lru_cache(maxsize=2)
def _read_ndvi(path: str, mtime: float):
    return pd.read_csv(path, dtype={"field_id": str})


def ndvi_monthly() -> pd.DataFrame | None:
    p = lina_dir() / "ndvi_monthly.csv"
    return _read_ndvi(str(p), p.stat().st_mtime) if p.exists() else None


def _files_key() -> tuple:
    """changes when the sample tables or a county file changes, so the cached neighbour tables are rebuilt"""
    files = [features.DATA_DIR / "fields" / "crop_history.parquet", *sorted(precomputed.directory().glob("*.parquet"))]
    return tuple((str(f), f.stat().st_mtime) for f in files if f.exists())


@lru_cache(maxsize=2)
def _neighbor_cached(key: tuple, cdl_to_slug: tuple):
    slug = dict(cdl_to_slug)
    parts_c, parts_s = [], []
    h = features.DATA_DIR / "fields" / "crop_history.parquet"
    if h.exists():
        hist = pd.read_parquet(h)
        parts_c.append(hist.assign(crop=hist["cdl_code"].map(slug).fillna("other"))[["field_id", "year", "crop"]])
        f = pd.read_parquet(features.DATA_DIR / "fields" / "fields.parquet", columns=["field_id", "state_fips"])
        parts_s.append(f.assign(state=f["state_fips"].map(precomputed.FIPS_STATE)).set_index("field_id")["state"])
    df = precomputed.frame()
    if len(df):
        parts_s.append(df["state"])
        hist_cols = [f"hist_{y}" for y in precomputed.HIST_YEARS]
        long = df[hist_cols].reset_index().melt(id_vars="field_id", var_name="col", value_name="cdl").dropna()
        long["year"] = long["col"].str[5:].astype(int)
        long["crop"] = long["cdl"].astype(int).map(slug).fillna("other")
        parts_c.append(long[["field_id", "year", "crop"]])
    return pd.concat(parts_c, ignore_index=True), pd.concat(parts_s)


def _neighbor_tables(a: Assets):
    """crop of every field and year + the state of every field, from the sample and the precomputed counties (cached)"""
    return _neighbor_cached(_files_key(), tuple((c["cdl_code"], s) for s, c in a.candidates.items()))


def bare_from_ndvi(ndvi: pd.DataFrame, field_id: str) -> dict[int, float]:
    """month -> share of years in which the field's NDVI was under the bare-soil level (months with observations only)"""
    d = ndvi[(ndvi["field_id"] == field_id) & (ndvi["n_obs"] > 0)]
    if d.empty:
        return {}
    return {int(m): float((g["ndvi_mean"] < BARE_NDVI).mean()) for m, g in d.groupby("month")}


# --------------------------------------------------------------------------- pieces of the response

def build_timeline(ctx, calendar_bare: list[float], ndvi_bare: dict[int, float], soil_drainage: str) -> list[dict]:
    m = ctx.monthly
    poorly = "poor" in str(soil_drainage or "").lower()
    out = []
    for i in range(12):
        et0, rain = m["et0"][i], m["precip"][i]
        deficit = float(np.clip((et0 - rain) / max(et0, 1.0), 0, 1))
        heat = float(np.clip(m["heat_days_32"][i] / 10.0, 0, 1))
        frost = float(np.clip(m["frost_days"][i] / DAYS[i], 0, 1))
        extreme = float(1 - math.exp(-m["extreme_rain_days"][i]))          # chance of at least one heavy-rain day
        use_ndvi = (i + 1) in ndvi_bare
        bare = ndvi_bare[i + 1] if use_ndvi else calendar_bare[i]
        flags = []
        if bare > FLAGS["bare"]:
            flags.append("bare")
        if deficit > FLAGS["drought"]:
            flags.append("drought")
        if heat > FLAGS["heat"]:
            flags.append("heat")
        if frost > FLAGS["frost"]:
            flags.append("frost")
        if extreme > FLAGS["extreme_rain"]:
            flags.append("extreme_rain")
        if poorly and extreme > FLAGS["waterlogging"]:
            flags.append("waterlogging")
        out.append({"month": i + 1, "bare_soil": round(bare, 2), "moisture_deficit": round(deficit, 2), "heat_stress": round(heat, 2),
                    "frost_risk": round(frost, 2), "extreme_precip": round(extreme, 2), "flags": flags,
                    "bare_soil_source": "landsat_ndvi" if use_ndvi else "crop_calendar"})
    return out


def _months_text(months: list[int], lang: str) -> str:
    """12-month numbers -> "Jul–Aug", or "Feb–Apr and Jul–Sep" when the months are not one run"""
    names = MONTHS[lang]
    runs, start = [], months[0]
    for prev, cur in zip(months, months[1:] + [None]):
        if cur != prev + 1:
            runs.append((start, prev))
            start = cur
    text = [names[a - 1] if a == b else f"{names[a - 1]}–{names[b - 1]}" for a, b in runs]
    return (" та " if lang == "uk" else " and ").join(text)


def risk_level(bare_days: float, peak_deficit: float, heat_days: float, peak_extreme: float) -> str:
    """DRAFT index 0-1 from four things (bare days, worst moisture deficit, hot days, heavy-rain chance).
    low / medium / high are the terciles of the index over 300 fields of IA, IL, NE and KS (0.54 and 0.64),
    so the level says how the field compares with the demo region"""
    idx = (min(bare_days / 300, 1) + peak_deficit + min(heat_days / 60, 1) + peak_extreme) / 4
    return "low" if idx < 0.54 else "medium" if idx < 0.64 else "high"


def build_summary(ctx, timeline: list[dict], lang: str) -> dict:
    t = RT[lang]
    bare_days = round(sum(x["bare_soil"] * DAYS[i] for i, x in enumerate(timeline)))
    dry = [x["month"] for x in timeline if "drought" in x["flags"]]
    deficit_ja = sum(max(0.0, ctx.monthly["et0"][i] - ctx.monthly["precip"][i]) for i in (6, 7))
    heat_days = sum(ctx.monthly["heat_days_32"])
    ndvi_used = any(x["bare_soil_source"] == "landsat_ndvi" for x in timeline)
    water = t["water_short"].format(months=_months_text(dry, lang)) if dry else t["water_ok"]
    peak_def = max(x["moisture_deficit"] for x in timeline)
    peak_ext = max(x["extreme_precip"] for x in timeline)
    return {
        "headline": t["headline"].format(bare=bare_days, water=water),
        "overall_risk": risk_level(bare_days, peak_def, heat_days, peak_ext),
        "key_numbers": [
            {"id": "bare_days", "label": t["kn_bare"], "value": bare_days, "unit": t["u_days"],
             "source_ids": ["landsat_ndvi"] if ndvi_used else ["csb"]},
            {"id": "jul_aug_water_deficit", "label": t["kn_deficit"], "value": round(deficit_ja), "unit": t["u_mm"], "source_ids": ["power"]},
            {"id": "heat_days", "label": t["kn_heat"], "value": round(heat_days), "unit": t["u_days"], "source_ids": ["power"]},
        ],
    }


HIGH_FIT = 30.0     # DRAFT: a fit_score from here up means "suits the field"


def build_suitability(rank: dict, a_roles: dict, prev_name: str, lang: str, irrigated=None) -> list[dict]:
    """two clear numbers per crop:
    fit_score       0-100, how well the FIELD suits the crop, without last year's crop (absolute scale)
    next_year_share %, advice for next year with the real previous crop and the transition matrix; adds up to 100
                    over the crops that are not blocked (cover crops are not main crops and get 0)
    rank follows next_year_share; `explanation` says in plain words why a crop with a high fit may not be on top."""
    t = RT[lang]
    roles = {c["crop"]: c["role"] for c in rank["top3"]}
    main = [c for c in rank["crops"] if c["status"] == "ok" and a_roles.get(c["crop"]) != "cover"]
    total = sum(c["score"] for c in main)
    shares = {c["crop"]: (100.0 * c["score"] / total if total > 0 else 0.0) for c in main}
    # round to one decimal and give the rounding remainder to the largest share, so the sum is exactly 100
    rounded = {k: round(v, 1) for k, v in shares.items()}
    if rounded:
        top = max(rounded, key=rounded.get)
        rounded[top] = round(rounded[top] + (100.0 - sum(rounded.values())), 1)

    rows = []
    for c in rank["crops"]:
        blocked = c["status"] == "blocked"
        rows.append({
            "crop": c["crop"], "name": c["name"], "group": c["group"], "fit_score": c["fit_score"],
            "next_year_share": 0.0 if blocked else rounded.get(c["crop"], 0.0), "rank": 0, "blocked": blocked,
            "block_reasons": list(c["blocked_reasons"]), "explanation": "", "top_factors": [f["text"] for f in c["main_factors"]],
            "top3_role": None if blocked else roles.get(c["crop"]), "model_class": c["model_class"],
            "role": "cover" if a_roles.get(c["crop"]) == "cover" else None,
            "parts": {**c["parts"], "score_raw": c["score"], "fit_prob": c["fit_prob"]},
            "_reason": c["transition_reason"],
        })
    rows.sort(key=lambda r: (r["blocked"], -r["next_year_share"], -r["fit_score"], r["crop"]))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    best = next((r for r in rows if not r["blocked"] and r["role"] != "cover"), None)
    for r in rows:
        reason = r.pop("_reason")
        fit, share = f"{r['fit_score']:.0f}", f"{r['next_year_share']:.0f}"
        if r["blocked"]:
            r["explanation"] = t["x_blocked"].format(reason=r["block_reasons"][0] if r["block_reasons"] else "")
        elif r["role"] == "cover":
            r["explanation"] = t["x_cover"]
        elif not r["model_class"]:
            r["explanation"] = t["x_rules_only"].format(fit=fit)
        elif best is not None and r["crop"] == best["crop"]:
            r["explanation"] = (t["x_top"] if r["fit_score"] >= HIGH_FIT else t["x_top_weak"]).format(fit=fit, share=share, prev=prev_name)
        elif r["fit_score"] >= HIGH_FIT and reason == "same_crop":
            r["explanation"] = t["x_same_crop"].format(fit=fit, share=share, prev=prev_name)
        elif r["fit_score"] >= HIGH_FIT and reason == "same_family":
            r["explanation"] = t["x_same_family"].format(fit=fit, share=share, prev=prev_name)
        elif r["fit_score"] >= HIGH_FIT and best is not None:
            r["explanation"] = t["x_other_prev"].format(fit=fit, share=share, prev=prev_name, top=best["name"],
                                                        top_share=f"{best['next_year_share']:.0f}")
        elif r["next_year_share"] >= 10:
            r["explanation"] = t["x_prev_helps"].format(fit=fit, share=share, prev=prev_name)
        else:
            r["explanation"] = t["x_low_fit"].format(fit=fit)
        ratio = r["parts"].get("water_ratio")
        if irrigated is not True and not r["blocked"] and r["role"] != "cover" and r["parts"].get("water", 1.0) < 0.7 and ratio is not None:
            r["explanation"] += t["x_water"].format(pct=f"{100 * ratio:.0f}")      # a strong water penalty is always said out loud
    return rows


def _flatten(tokens: list[str]) -> list[str]:
    return [c for t in tokens for c in components(t)]


# --------------------------------------------------------------------------- the entry point

def analyze_real(req) -> dict:
    a = assets()
    cfg = {**settings(), "horizon_years": req.options.horizon_years}
    lang = req.options.language
    t = RT[lang]
    fi = req.farmer_input
    scenario = (req.scenario.temp_delta_c, req.scenario.precip_change_pct)

    forced = None
    if fi.current_rotation:
        bad = [c for c in fi.current_rotation if c not in a.candidates or a.candidates[c].get("role") == "cover"]
        if bad:
            raise invalid_input(t["rotation_unknown_crop"].format(crop=bad[0]), field="farmer_input.current_rotation", crop=bad[0])
        forced = list(fi.current_rotation)

    ctx = features.get_context(req, a, scenario)
    ctx = type(ctx)(**{**ctx.__dict__, "irrigated": fi.irrigated})
    excluded = set(fi.excluded_crops)

    # last-season stress from Landsat NDVI (only when Lina's file exists)
    ndvi = ndvi_monthly()
    stress, ndvi_bare = None, {}
    if ndvi is not None:
        crop_of, state_of = _neighbor_tables(a)
        stress = compute_stress(ndvi, crop_of, state_of, req.field.field_id, ctx.target_year - 1, ctx.prev_crops[0], cfg["stress"])
        ndvi_bare = bare_from_ndvi(ndvi, req.field.field_id)

    prio = req.priorities.model_dump()
    plan = plan_rotations(ctx, a, priorities=prio, lang=lang, n_strategies=req.options.n_strategies, stress=stress, forced_cycle=forced,
                          farmer_input={"irrigated": fi.irrigated, "has_livestock": fi.has_livestock, "excluded_crops": list(excluded)},
                          settings=cfg)
    rank = rank_crops(ctx, a, lang, fi.irrigated, explain=True, fit=True, excluded=excluded)

    cur = plan["details"]["current"]
    calendar = agro.monthly_bare(cur["steps"], cur["covers"], cfg["cover"]["crop"])
    timeline = build_timeline(ctx, calendar, ndvi_bare, ctx.soil.get("drainage_class"))
    summary = build_summary(ctx, timeline, lang)
    last = (ctx.history_rich or ctx.history).get(ctx.target_year - 1)
    suitability = build_suitability(rank, {k: v.get("role") for k, v in a.candidates.items()},
                                    crop_name(last, lang) if last else crop_name("other", lang), lang, fi.irrigated)

    # ---- warnings and status
    warnings = list(ctx.notes)
    if ndvi is None:
        warnings.append(t["w_ndvi"])
    if ctx.smap_deficit_share is None:
        warnings.append(t["w_smap"])
    if ctx.twi is None:
        warnings.append(t["w_twi"])
    if ctx.slope_source != "nasadem":
        warnings.append(t["w_dem"])
    om = ctx.soil.get("om_pct")
    if om is not None and om > 20:
        warnings.append(t["w_organic"])
    cr = plan["current_rotation"]
    if not cr["clean"]:
        warnings.append(t["w_rotation"])
    have = len(plan["strategies"]) - 1
    if have < req.options.n_strategies:
        warnings.append(t["w_few"].format(have=have, want=req.options.n_strategies))
    warnings.append(t["src_precomputed"] if ctx.provenance in ("precomputed", "tables") else t["src_on_the_fly"])

    # ---- sources: only the ones really used
    used = set(ALWAYS_USED)
    for kn in summary["key_numbers"]:
        used.update(kn["source_ids"])
    for s in plan["strategies"]:
        for e in s["evidence"]:
            used.update(e["source_ids"])
    if ndvi is not None and (stress and stress.active or ndvi_bare):
        used.add("landsat_ndvi")
    if ctx.slope_source == "nasadem" or ctx.twi is not None:
        used.add("nasadem")
    if ctx.smap_deficit_share is not None:
        used.add("smap")
    sources = [{"id": s[0], "name": s[1], "variable": s[2], "resolution": s[3], "period": s[4]} for s in SOURCES[lang] if s[0] in used]

    return {
        "request_id": req.request_id or str(uuid.uuid4()),
        "field_id": req.field.field_id,
        "model_version": MODEL_VERSION_REAL,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "partial" if warnings_need_partial(warnings, t) else "ok",
        "detected_rotation": {"sequence": _flatten(cr["sequence"]), "label": cr["label"], "confidence": cr["confidence"],
                              "years_used": cr["years_used"], "source": cr["source"], "cycle_years": cr["cycle_years"]},
        "summary": summary,
        "vulnerability_timeline": timeline,
        "strategies": plan["strategies"],
        "crop_suitability": suitability,
        "sources": sources,
        "warnings": warnings,
        "score_notes": plan["score_notes"],
        "feature_source": ctx.provenance,
        "disclaimer": DISCLAIMER[lang],
    }


def warnings_need_partial(warnings: list[str], t: dict) -> bool:
    """partial only when a data layer the analysis needs is missing: NDVI or SMAP, or the soil is organic (out of the training
    domain). everything else (no TWI, SSURGO slope instead of NASADEM, provenance line, rotation notes) is just a warning."""
    return any(w in warnings for w in (t["w_ndvi"], t["w_smap"], t["w_organic"]))
