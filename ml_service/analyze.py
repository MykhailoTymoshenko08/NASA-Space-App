"""Orchestrates one /analyze call: detect rotation -> evaluate current + candidates ->
priority-weighted ranking -> contract response. Deterministic: same input, same output."""
import hashlib
import uuid
from datetime import datetime, timezone

from . import MODEL_VERSION, COVERAGE_STATES
from . import crops as crop_db
from .climate import Context, build_timeline, heat_days, Rotation
from .errors import invalid_input, out_of_coverage
from .rotations import (SCORE_KEYS, Candidate, Evaluation, build_candidates, detect_rotation,
                        evaluate, mains_of, overall, plain)
from .schemas import AnalyzeRequest, AnalyzeResponse
from .texts import DISCLAIMER, MONTHS, SOURCES, T

SOIL_DEFAULTS = {"om_pct": 3.0, "awc": 0.17, "slope_pct": 2.0, "drainage": "somewhat poorly drained"}
DEFAULT_MAINS = ["corn", "soybean"]


def _unit(field_id: str, salt: str) -> float:
    """stable pseudo-random number in [0, 1] derived from the field id"""
    return int(hashlib.sha256((salt + field_id).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _names(mains: list[str], lang: str) -> list[str]:
    """crop names with consecutive repeats collapsed: alfalfa x3 -> 'Alfalfa (3 yr)'"""
    key = "name_uk" if lang == "uk" else "name_en"
    out, i = [], 0
    while i < len(mains):
        j = i
        while j < len(mains) and mains[j] == mains[i]:
            j += 1
        name = getattr(crop_db.CATALOG[mains[i]], key)
        out.append(name if j - i == 1 else f"{name} ({j - i} {'р.' if lang == 'uk' else 'yr'})")
        i = j
    return out


def _base(mains: list[str], lang: str) -> str:
    return " – ".join(_names(mains, lang))


def _label(mains: list[str], lang: str) -> str:
    tx = T[lang]
    base = _base(mains, lang)
    if len(mains) == 1:
        return tx["label_continuous"].format(base=base)
    return tx["label_n_year"].format(base=base, n=len(mains))


def _months_text(months: list[int], lang: str) -> str:
    names = MONTHS[lang]
    if not months:
        return ""
    return names[months[0] - 1] if len(months) == 1 else f"{names[months[0] - 1]}–{names[months[-1] - 1]}"


def _resolve_soil(req: AnalyzeRequest, warnings: list[str], gaps: list[str], lang: str) -> dict:
    s = req.field.soil
    if s is None:
        warnings.append(T[lang]["warn_soil"])
        gaps.append(T[lang]["gap_soil"])
        return dict(SOIL_DEFAULTS)
    values = {
        "om_pct": s.organic_matter_pct, "awc": s.awc_cm_cm,
        "slope_pct": s.slope_pct, "drainage": s.drainage_class,
    }
    if any(v is None for v in values.values()):
        gaps.append(T[lang]["gap_soil"])
    return {k: (v if v is not None else SOIL_DEFAULTS[k]) for k, v in values.items()}


def _current_rotation(req: AnalyzeRequest, warnings: list[str], gaps: list[str], lang: str):
    """returns (mains, confidence, years_used, source)"""
    tx = T[lang]
    fi = req.farmer_input
    if fi.current_rotation:
        mains = []
        for slug in fi.current_rotation:
            crop = crop_db.CATALOG.get(slug)
            if crop is None or crop.is_cover:
                raise invalid_input(f"farmer_input.current_rotation: unknown or non-main crop '{slug}'",
                                    field="farmer_input.current_rotation", crop=slug)
            mains.append(slug)
        return mains, 0.95, [], "farmer_input"

    history = sorted(req.field.crop_history or [], key=lambda h: h.year)
    known, unknown = [], []
    for h in history:
        crop = crop_db.resolve(h.crop, h.cdl_code)
        if crop is None:
            unknown.append(h.crop)
        elif not crop.is_cover:
            known.append((h.year, crop.slug))
    if unknown:
        warnings.append(tx["warn_unknown_crops"].format(crops=", ".join(sorted(set(unknown)))))
    if len(known) >= 2:
        mains, conf = detect_rotation([c for _, c in known])
        return mains, conf, [known[0][0], known[-1][0]], "csb"

    # nothing usable: deterministic default so the same field always gets the same answer
    warnings.append(tx["warn_history"])
    gaps.append(tx["gap_history"])
    mains = list(DEFAULT_MAINS) if _unit(req.field.field_id, "rot") < 0.5 else list(reversed(DEFAULT_MAINS))
    return mains, 0.4, [], "model_prior"


def _evaluate_all(current: Rotation, candidates: list[Candidate], ctx: Context, weights: dict):
    cur_eval = evaluate(current, ctx)
    cur_overall = overall(cur_eval.scores, weights)
    evals = []
    for c in candidates:
        e = evaluate(c.rotation, ctx)
        evals.append((c, e, overall(e.scores, weights)))
    evals.sort(key=lambda t: (-t[2], t[0].kind))
    return cur_eval, cur_overall, evals


def _scores_dict(e: Evaluation, ov: float) -> dict[str, int]:
    out = {k: int(round(e.scores[k])) for k in SCORE_KEYS}
    out["overall"] = int(round(ov))
    return out


def _sequence(rotation: Rotation) -> list[dict]:
    items = []
    for i, (main, covers) in enumerate(rotation, start=1):
        items.append({"year": i, "season": "main", "crop": main})
        items.extend({"year": i, "season": "cover", "crop": c} for c in covers)
    return items


def _metrics(e: Evaluation) -> dict:
    return {
        "water_use_mm_yr": round(e.water_use),
        "n_fixed_kg_ha_yr": round(e.n_fixed),
        "bare_days_yr": e.bare_days,
        "erosion_t_ha_yr": round(e.erosion, 1),
    }


def _overall_risk(timeline: list[dict], bare: int, heat: float) -> str:
    peak_def = max(t["moisture_deficit"] for t in timeline)
    peak_extreme = max(t["extreme_precip"] for t in timeline)
    idx = (min(bare / 250, 1) + peak_def + min(heat / 40, 1) + min(peak_extreme * 4, 1)) / 4
    return "low" if idx < 0.35 else "medium" if idx < 0.55 else "high"


def run_analysis(req: AnalyzeRequest) -> AnalyzeResponse:
    state = req.field.admin.state
    if state not in COVERAGE_STATES:
        raise out_of_coverage(
            "Field is outside the demo region.", state=state, covered_states=list(COVERAGE_STATES))

    lang = req.options.language
    tx = T[lang]
    warnings: list[str] = []
    gaps: list[str] = []

    soil = _resolve_soil(req, warnings, gaps, lang)
    mains, det_conf, years_used, source = _current_rotation(req, warnings, gaps, lang)
    partial = bool(warnings)
    if req.farmer_input.irrigated is None:
        gaps.append(tx["gap_irrigation"])
    if req.farmer_input.has_livestock is None:
        gaps.append(tx["gap_livestock"])

    ctx = Context(
        state=state, temp_delta=req.scenario.temp_delta_c, precip_pct=req.scenario.precip_change_pct,
        irrigated=req.farmer_input.irrigated, has_livestock=req.farmer_input.has_livestock,
        om_pct=soil["om_pct"], awc=soil["awc"], slope_pct=soil["slope_pct"],
        drainage=soil["drainage"], language=lang,
    )
    weights = req.priorities.model_dump()

    current = plain(mains)
    excluded = set(req.farmer_input.excluded_crops)
    candidates = build_candidates(mains, excluded)
    cur_eval, cur_overall, ranked = _evaluate_all(current, candidates, ctx, weights)

    want = req.options.n_strategies
    if len(ranked) < want:
        warnings.append(tx["warn_few"].format(have=len(ranked), want=want))
        partial = True
    ranked = ranked[:want]

    timeline = build_timeline(current, ctx)
    heat = heat_days(ctx)
    cur_scores = _scores_dict(cur_eval, cur_overall)

    # mock "historical" jul-aug soil moisture anomaly (SMAP will replace this), shifted by the scenario
    base_anom = -20 + 25 * _unit(req.field.field_id, "smap")
    scen = ((1 + ctx.precip_pct / 100) / (1 + 0.03 * ctx.temp_delta) - 1) * 100
    anomaly = round(base_anom + 0.8 * scen)

    drought_months = [t["month"] for t in timeline if "drought" in t["flags"]]
    water_phrase = (tx["water_short"].format(months=_months_text(drought_months, lang))
                    if drought_months else tx["water_ok"])
    headline = tx["headline"].format(bare=cur_eval.bare_days, water=water_phrase)

    key_numbers = [
        {"id": "bare_days", "label": tx["kn_bare"], "value": cur_eval.bare_days, "unit": "days" if lang == "en" else "дн.",
         "source_ids": ["landsat_ndvi"]},
        {"id": "jul_aug_moisture_anomaly", "label": tx["kn_moisture"], "value": anomaly, "unit": "%",
         "source_ids": ["smap"]},
        {"id": "heat_days", "label": tx["kn_heat"], "value": round(heat), "unit": "days" if lang == "en" else "дн.",
         "source_ids": ["power"]},
        {"id": "erosion_t_ha_yr", "label": tx["kn_erosion"], "value": round(cur_eval.erosion, 1),
         "unit": "t/ha/yr" if lang == "en" else "т/га/рік", "source_ids": ["nasadem", "ssurgo"]},
    ]

    # ---- strategies
    risks = []
    if cur_eval.bare_days > 120:
        risks.append(tx["cur_risk_bare"].format(bare=cur_eval.bare_days))
    if heat >= 10:
        risks.append(tx["cur_risk_heat"].format(heat=round(heat)))
    if drought_months:
        risks.append(tx["cur_risk_water"].format(months=_months_text(drought_months, lang)))
    if source == "csb":
        why_cur = tx["why_csb"].format(y0=years_used[0], y1=years_used[1])
    else:
        why_cur = tx["why_farmer"] if source == "farmer_input" else tx["why_prior"]

    strategies = [{
        "id": "current", "is_current": True,
        "name": tx["current_prefix"].format(name=_base(mains, lang)),
        "sequence": _sequence(current), "scores": cur_scores, "delta_vs_current": None,
        "metrics": _metrics(cur_eval), "why": why_cur, "evidence": [],
        "benefits": [tx["cur_benefit"]], "risks": risks, "data_gaps": list(gaps),
        "check_with_agronomist": [tx["cur_check"]], "confidence": round(det_conf, 2),
    }]

    for i, (cand, ev, ov) in enumerate(ranked, start=1):
        scores = _scores_dict(ev, ov)
        k = tx["kinds"][cand.kind]
        cand_mains = mains_of(cand.rotation)
        params = {
            "bare_now": cur_eval.bare_days, "bare_new": ev.bare_days,
            "bare_cut": round(100 * (cur_eval.bare_days - ev.bare_days) / max(cur_eval.bare_days, 1)),
            "nfix_new": round(ev.n_fixed), "water_new": round(ev.water_use),
        }
        strategies.append({
            "id": f"s{i}", "is_current": False,
            "name": tx["names"][cand.kind].format(base=_base(cand_mains, lang)),
            "sequence": _sequence(cand.rotation),
            "scores": scores,
            "delta_vs_current": {key: scores[key] - cur_scores[key] for key in (*SCORE_KEYS, "overall")},
            "metrics": _metrics(ev),
            "why": k["why"].format(**params),
            "evidence": [
                {"text": tx["ev_bare"].format(a=cur_eval.bare_days, b=ev.bare_days), "source_ids": ["landsat_ndvi"]},
                {"text": tx["ev_erosion"].format(a=round(cur_eval.erosion, 1), b=round(ev.erosion, 1),
                                                 slope=soil["slope_pct"], om=soil["om_pct"]),
                 "source_ids": ["nasadem", "ssurgo"]},
                {"text": tx["ev_water"].format(a=round(cur_eval.water_use), b=round(ev.water_use), anom=anomaly),
                 "source_ids": ["smap", "power"]},
            ],
            "benefits": [b.format(**params) for b in k["benefits"]],
            "risks": [r.format(**params) for r in k["risks"]],
            "data_gaps": list(gaps),
            "check_with_agronomist": [c.format(**params) for c in k["check"]],
            "confidence": round(max(0.2, min(0.95, det_conf * 0.95 - 0.04 * cand.complexity)), 2),
        })

    sources = [
        {"id": s[0], "name": s[1], "variable": s[2], "resolution": s[3], "period": s[4]}
        for s in SOURCES[lang]
    ]

    return AnalyzeResponse.model_validate({
        "request_id": req.request_id or str(uuid.uuid4()),
        "field_id": req.field.field_id,
        "model_version": MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "partial" if partial else "ok",
        "detected_rotation": {
            "sequence": mains, "label": _label(mains, lang), "confidence": round(det_conf, 2),
            "years_used": years_used, "source": source,
        },
        "summary": {
            "headline": headline,
            "overall_risk": _overall_risk(timeline, cur_eval.bare_days, heat),
            "key_numbers": key_numbers,
        },
        "vulnerability_timeline": timeline,
        "strategies": strategies,
        "sources": sources,
        "warnings": warnings,
        "disclaimer": DISCLAIMER[lang],
    })
