"""Rotation planner: from the crop ranking to 3-year rotations.

1. the CURRENT rotation is read from the CSB history (last 4-8 years) and continued for the planning horizon;
2. CANDIDATES are all chains of 3 years made of crops that are not blocked. a step is scored by the crop ranking
   (ml_service/ranking.py) with the previous step as the previous crop (the first step uses the real last year);
   chain score = product of the step scores;
3. a winter COVER crop (cereal rye) can be added after crops harvested in autumn, if the rules allow it;
4. the AGRO CALCULATOR (ml_service/agro.py) scores every variant: bare days, nitrogen, water (Kc x ET0), erosion (RUSLE), pests;
5. the farmer's priorities weigh the five calculator scores together with "fit" (how well the crops suit the field)
   into a 0-100 score; the delta is against the current rotation;
6. the top alternatives are picked by DIFFERENT LOGIC (cover / small grains / drought-tolerant / perennial / other crop set),
   not three near-copies of the best one.

Output follows the `strategies` format of docs/api_contract.md; extra numbers (nitrogen balance, pest cycle, fit) are in `details`.
All chains are enumerated (7^3 = 343), no beam search needed.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, replace

import numpy as np
import yaml

from . import agro
from .cdl import first_component, last_component
from .feature_text import crop_name
from .ranking import ROOT, Assets, FieldContext, rank_crops
from .stress import StressSignal, stress_multipliers
from .texts import SOURCES

PRIORITY_KEYS = ("water", "soil_health", "nitrogen", "erosion", "income")
LEGUMES = {"soybean", "alfalfa"}


def load_settings(path=ROOT / "config" / "rotation_settings.yaml") -> dict:
    return yaml.safe_load(open(path))


# --------------------------------------------------------------------------- 1. the current rotation

@dataclass
class Detected:
    steps: list[str]          # the cycle continued for the planning horizon, starting with next year
    cycle: list[str]          # one cycle, written starting right after a legume when there is one
    confidence: float
    window: int
    period: int
    agreement: float
    years_used: list[int]
    clean: bool               # a stable repeating pattern was found


def detect_rotation(history: dict, target_year: int, horizon: int, cfg: dict) -> Detected:
    """smallest repeating cycle (1-4 years) that holds over the last 8, 6 or 4 years; longest window first."""
    years = sorted(y for y in history if y < target_year)
    seq = [history[y] for y in years]
    found = None
    for w in cfg["windows"]:
        if len(seq) < w:
            continue
        x = seq[-w:]
        for p in cfg["periods"]:
            pairs = w - p
            if pairs < 2:
                continue
            agree = float(np.mean([x[i] == x[i + p] for i in range(pairs)]))
            if agree >= cfg["min_agreement"]:
                found = (w, p, agree)
                break
        if found:
            break
    clean = found is not None
    if not found:   # no stable pattern: the best cycle we can find, with low confidence
        w = min(len(seq), 8)
        x = seq[-w:]
        best = max(((float(np.mean([x[i] == x[i + p] for i in range(w - p)])) if w - p >= 1 else 0.0, p) for p in cfg["periods"]))
        found = (w, best[1], best[0])
    w, p, agree = found
    if not seq:
        return Detected(["unknown"] * horizon, ["unknown"], 0.2, 0, 1, 0.0, [], False)
    p = min(p, len(seq))
    ext = list(seq)
    for _ in range(max(horizon, p)):
        ext.append(ext[-p])
    proj = ext[len(seq):]            # the cycle continued into the future
    steps, cycle = proj[:horizon], proj[:p]
    legume_at = [i for i, c in enumerate(cycle) if c in LEGUMES]
    if legume_at:   # rotate so that the cycle ends with a legume: "Corn - Corn - Soybean"
        k = (legume_at[-1] + 1) % p
        cycle = cycle[k:] + cycle[:k]
    conf = agree * min(1.0, (w - p) / 4) if clean else 0.3 * agree
    return Detected(steps=steps, cycle=cycle, confidence=float(np.clip(conf, 0.2, 0.95)), window=w, period=p,
                    agreement=agree, years_used=[years[-w], years[-1]] if years else [], clean=clean)


def forced_rotation(cycle: list[str], last_token: str | None, horizon: int) -> Detected:
    """the farmer says what the rotation is: continue it from the crop after the one grown last year."""
    cyc, p = list(cycle), len(cycle)
    last = last_component(last_token) if last_token else None
    idx = max((i for i, c in enumerate(cyc) if last_component(c) == last), default=None)
    start = 0 if idx is None else (idx + 1) % p
    steps = [cyc[(start + k) % p] for k in range(horizon)]
    return Detected(steps=steps, cycle=cyc, confidence=0.95, window=0, period=p, agreement=1.0, years_used=[], clean=True)


# --------------------------------------------------------------------------- the planner

class Planner:
    def __init__(self, ctx: FieldContext, a: Assets, settings: dict, *, irrigated=None, has_livestock=None, lang="uk",
                 stress: StressSignal | None = None):
        self.ctx, self.a, self.cfg, self.lang = ctx, a, settings, lang
        self.irrigated = ctx.irrigated if irrigated is None else irrigated
        self.livestock = has_livestock
        self.stress = stress or StressSignal()
        self.main = [c for c, v in a.candidates.items() if v.get("role") != "cover"]
        self._cache: dict = {}
        self._first_extra = stress_multipliers(self.stress, a.candidates, a.transition["families"], settings["stress"], lang)
        self.cover_blocked: list[str] = []

    # one step of a chain: how every crop scores given the previous two crops
    def step(self, prev1: str, prev2: str, later: bool) -> dict:
        key = (prev1, prev2, later)
        if key not in self._cache:
            c = replace(self.ctx, prev_crops=[prev1, prev2], climate_lag1=self.ctx.climate_norm if later else self.ctx.climate_lag1)
            r = rank_crops(c, self.a, self.lang, self.irrigated, explain=False, extra=None if later else self._first_extra)
            scores = {x["crop"]: x["score"] for x in r["crops"] if x["crop"] in self.main}
            self._cache[key] = {"scores": scores, "best": max(scores.values()), "result": r}
        return self._cache[key]

    def chain(self, steps: list[str]) -> tuple[float, float]:
        """(chain score = product of steps, fit 0-100)."""
        p1, p2 = self.ctx.prev_crops[0], self.ctx.prev_crops[1]
        score, rel = 1.0, []
        for j, crop in enumerate(steps):
            st = self.step(p1, p2, later=j > 0)
            if crop in self.main:
                s = st["scores"][crop]
                score *= s
                rel.append(max(s, 1e-9) / st["best"] if st["best"] > 0 else 1.0)   # everything blocked: no information
            p1, p2 = crop, p1
        fit = 100 * float(np.exp(np.mean(np.log(np.power(rel, self.cfg["fit_gamma"]))))) if rel else 100.0
        return score, fit

    def cover_slots(self, steps: list[str]) -> list[bool]:
        """where a winter cover fits: after crops harvested early, not before crops sown at the same time."""
        cc = self.cfg["cover"]
        n = len(steps)
        first = self.step(self.ctx.prev_crops[0], self.ctx.prev_crops[1], False)["result"]
        rye = next(c for c in first["crops"] if c["crop"] == cc["crop"])
        if rye["status"] == "blocked":
            self.cover_blocked = rye["blocked_reasons"]
            return [False] * n
        return [last_component(steps[j]) in cc["allowed_after"] and first_component(steps[(j + 1) % n]) not in cc["not_before"]
                for j in range(n)]

    def agro(self, steps: list[str], covers: list[bool]) -> agro.AgroResult:
        c = self.ctx
        return agro.evaluate(steps, covers, c.prev_crops[0], et0_monthly=c.et0_monthly, precip_annual=c.precip_annual,
                             kw_factor=c.soil["kw_factor"], slope_pct=c.slope_pct, om_pct=c.soil["om_pct"], awc=c.soil["awc_cm_cm"],
                             irrigated=self.irrigated, has_livestock=self.livestock, temp_delta_c=c.scenario[0],
                             precip_change_pct=c.scenario[1], cover_crop=self.cfg["cover"]["crop"])

    def variant(self, steps: list[str], covers: list[bool], weights: dict) -> dict:
        score, fit = self.chain(steps)
        r = self.agro(steps, covers)
        sc = dict(r.scores)
        sc["soil_health"] -= self.cfg["repeat_soil_penalty"] * len(r.pest_pairs)
        if self.stress.active and covers[0]:
            sc["soil_health"] += self.cfg["stress"]["cover_bonus_points"] * self.stress.intensity
        sc["soil_health"] = float(np.clip(sc["soil_health"], 0, 100))
        w = {**weights, "fit": self.cfg["fit_weight"]}
        parts = {**sc, "fit": fit}
        overall = sum(w[k] * parts[k] for k in parts) / sum(w.values())
        return {"steps": list(steps), "covers": list(covers), "agro": r, "scores": sc, "fit": fit, "chain_score": score, "overall": overall}


# --------------------------------------------------------------------------- picking by logic

def logic_tag(steps: list[str], covers: list[bool], current_steps: list[str], a: Assets) -> str:
    if any(covers) and steps == current_steps:
        return "cover"
    if "alfalfa" in steps:
        return "perennial"
    if "sorghum" in steps:
        return "drought"
    if any(c in ("winter_wheat", "oats", "barley") for c in steps):
        return "diversified"
    return "switch"


def pick_alternatives(variants: list[dict], current: dict, n: int, min_fit: float, max_loss: float, order: list[str]) -> list[dict]:
    """best variant of each logic, so the alternatives are different ideas and not near-copies.
    an alternative must (a) be realistic for the field (fit), (b) not be much worse than the current rotation,
    (c) use other crops than the current one, except the "same crops + cover" idea."""
    cur_set = set(current["steps"])
    ok = [v for v in variants if v["chain_score"] > 0 and v["fit"] >= min_fit and (set(v["steps"]) != cur_set or v["tag"] == "cover")]
    pool = [v for v in ok if v["overall"] >= current["overall"] - max_loss] or ok   # nothing close enough: take what there is
    pool.sort(key=lambda v: (-v["overall"], -v["chain_score"]))
    picked, sets = [], set()
    for tag in order:                   # the ideas in a fixed order; the best variant of each
        v = next((x for x in pool if x["tag"] == tag and frozenset(x["steps"]) not in sets), None)
        if v:
            picked.append(v)
            sets.add(frozenset(v["steps"]))
        if len(picked) == n:
            break
    picked.sort(key=lambda v: -v["overall"])
    return picked


# --------------------------------------------------------------------------- texts

TX = {
    "uk": {
        "current": "Поточна: {name}", "cover_suffix": " + покривне жито", "other": "інше (невідомо)",
        "logic": {
            "cover": "Ті самі культури, але взимку ґрунт закриває жито.",
            "perennial": "Багаторічна люцерна на кілька років: майже без ерозії й з великим азотним кредитом.",
            "drought": "Сорго замість найвологоємніших культур: стійкіше до спеки й посухи.",
            "diversified": "Малі зернові розривають цикли шкідників і розподіляють погодні ризики.",
            "switch": "Інший набір основних культур, який за вашими пріоритетами працює краще.",
        },
        "why_current": "Базова сівозміна визначена за історією CSB {y0}–{y1} (цикл {p} р., збіг {agree:.0%}), продовжена на {h} роки.",
        "why_farmer": "Сівозміну вказав фермер; продовжена на {h} роки.",
        "why_current_weak": "Чіткого повторюваного циклу в історії {y0}–{y1} не знайдено; взято найближчий ({p} р.), довіра низька.",
        "why_numbers": "Голих днів {b0:.0f}→{b1:.0f} на рік, ерозія {e0:.1f}→{e1:.1f} т/га, азот {n0:+.0f}→{n1:+.0f} кг/га.",
        "ev_bare": "Голих днів ґрунту: {a:.0f} → {b:.0f} на рік (за календарем культур)",
        "ev_erosion": "Ерозія {a:.1f} → {b:.1f} т/га/рік (RUSLE: опади {p:.0f} мм/рік, K={k:.2f}, ухил {s:.1f}%)",
        "ev_water": "Водоспоживання {a:.0f} → {b:.0f} мм/рік (Kc × ET0 за FAO-56; опади {p:.0f} мм/рік)",
        "ev_nitrogen": "Баланс азоту {a:+.0f} → {b:+.0f} кг/га/рік (фіксація бобовими {f:.0f} кг/га/рік)",
        "ev_stress": "NDVI минулого сезону на {pct:.0f}% нижче за сусідів (z = {z:.1f})",
        "ev_scenario": "Сценарій: {t:+.1f}°C, опади {p:+.0f}%: водний баланс вегетації став {wb:.0f} мм",
        "ben_bare": "Голих днів менше на {x:.0f}%", "ben_erosion": "Ерозія менша на {x:.0f}%",
        "ben_nitrogen": "Кращий баланс азоту: {x:+.0f} кг/га/рік", "ben_pest": "Розриває цикл шкідників (немає повтору культури)",
        "ben_income": "Дохід вищий на {x:.0f} п.", "ben_water": "Водоспоживання менше на {x:.0f} мм/рік",
        "ben_none": "Порівнянні показники з поточною сівозміною",
        "risk_water": "Споживає більше води: +{x:.0f} мм/рік", "risk_income": "Дохід нижчий на {x:.0f} п.",
        "risk_fit": "Нетипово для цього регіону: модель дає такій культурі низький шанс",
        "risk_repeat": "Повтор тієї ж культури: цикл шкідників не розірваний",
        "risk_cover": "Жито витрачає весняну вологу й може придушити сходи наступної культури",
        "risk_forage": "Люцерні потрібен ринок сіна або худоба",
        "risk_stress": "Минулий сезон був слабким (NDVI на {pct:.0f}% нижче за сусідів): повтор культури ризикованіший",
        "check": {
            "cover": ["Терміни висіву й термінації жита перед основною культурою", "Вплив жита на вологу весною"],
            "perennial": ["Попит на корми й ціни на сіно", "Закладання та знищення травостою"],
            "drought": ["Місцеві контракти й базис на сорго", "Підбір гібрида під ваш регіон"],
            "diversified": ["Техніка й праця для додаткової культури", "Наявність насіння та елеватора"],
            "switch": ["Чи відповідає новий набір культур вашим контрактам і техніці"],
        },
        "gap_irrigation": "Немає даних про зрошення на рівні поля",
        "gap_irrigation_set": "Якщо поле зрошується, вкажіть irrigated=true: рекомендація зміниться", "gap_livestock": "Невідомо, чи є худоба / потреба в кормах",
        "gap_slope": "Ухил береться зі SSURGO (NASADEM ще немає)", "gap_income": "Дохід — відносний індекс, а не гроші",
        "gap_stress": "Немає NDVI від Ліни: правило стресу минулого сезону вимкнене",
        "gap_cover_blocked": "Покривна культура не дозволена правилами: {why}",
        "gap_nothing_fits": "Жодна культура не проходить жорсткі фільтри для цього поля, альтернативи не пропонуються",
    },
    "en": {
        "current": "Current: {name}", "cover_suffix": " + cereal rye cover", "other": "other (unknown)",
        "logic": {
            "cover": "The same crops, with rye covering the soil in winter.",
            "perennial": "Perennial alfalfa for a few years: almost no erosion and a big nitrogen credit.",
            "drought": "Sorghum instead of the thirstiest crops: better with heat and drought.",
            "diversified": "Small grains break pest cycles and spread weather risk.",
            "switch": "A different set of main crops that works better for your priorities.",
        },
        "why_current": "Baseline read from the CSB history {y0}-{y1} (cycle of {p} years, {agree:.0%} match), continued for {h} years.",
        "why_farmer": "Rotation stated by the farmer; continued for {h} years.",
        "why_current_weak": "No stable repeating cycle in {y0}-{y1}; the closest one ({p} years) is used, low confidence.",
        "why_numbers": "Bare days {b0:.0f}->{b1:.0f} a year, erosion {e0:.1f}->{e1:.1f} t/ha, nitrogen {n0:+.0f}->{n1:+.0f} kg/ha.",
        "ev_bare": "Bare soil days: {a:.0f} -> {b:.0f} a year (from crop calendars)",
        "ev_erosion": "Erosion {a:.1f} -> {b:.1f} t/ha/yr (RUSLE: rain {p:.0f} mm/yr, K={k:.2f}, slope {s:.1f}%)",
        "ev_water": "Water use {a:.0f} -> {b:.0f} mm/yr (Kc x ET0, FAO-56; rain {p:.0f} mm/yr)",
        "ev_nitrogen": "Nitrogen balance {a:+.0f} -> {b:+.0f} kg/ha/yr (legume fixation {f:.0f} kg/ha/yr)",
        "ev_stress": "Last season's NDVI was {pct:.0f}% below the neighbours (z = {z:.1f})",
        "ev_scenario": "Scenario: {t:+.1f} C, rain {p:+.0f}%: growing-season water balance is {wb:.0f} mm",
        "ben_bare": "Bare days down {x:.0f}%", "ben_erosion": "Erosion down {x:.0f}%",
        "ben_nitrogen": "Better nitrogen balance: {x:+.0f} kg/ha/yr", "ben_pest": "Breaks the pest cycle (no crop repeats)",
        "ben_income": "Income higher by {x:.0f} points", "ben_water": "Water use down {x:.0f} mm/yr",
        "ben_none": "Comparable to the current rotation",
        "risk_water": "Uses more water: +{x:.0f} mm/yr", "risk_income": "Income lower by {x:.0f} points",
        "risk_fit": "Unusual for this region: the model gives such a crop a low chance",
        "risk_repeat": "Same crop repeats: pest cycle not broken",
        "risk_cover": "Rye uses spring moisture and may suppress the next crop's emergence",
        "risk_forage": "Alfalfa needs a hay market or livestock",
        "risk_stress": "Last season was weak (NDVI {pct:.0f}% below neighbours): repeating a crop is riskier",
        "check": {
            "cover": ["Rye seeding and termination dates before the main crop", "Effect of rye on spring moisture"],
            "perennial": ["Forage demand and hay prices", "Stand establishment and termination"],
            "drought": ["Local sorghum contracts and basis", "Hybrid choice for your region"],
            "diversified": ["Equipment and labour for an extra crop", "Seed and elevator availability"],
            "switch": ["Whether the new set of crops fits your contracts and equipment"],
        },
        "gap_irrigation": "No field-level irrigation data",
        "gap_irrigation_set": "If the field is irrigated, set irrigated=true — the recommendation will change", "gap_livestock": "Livestock / forage demand unknown",
        "gap_slope": "Slope comes from SSURGO (NASADEM not available yet)", "gap_income": "Income is a relative index, not money",
        "gap_stress": "No NDVI from Lina: the last-season stress rule is off",
        "gap_cover_blocked": "A cover crop is not allowed by the rules: {why}",
        "gap_nothing_fits": "No crop passes the hard filters for this field, no alternatives are offered",
    },
}


def _label(steps: list[str], lang: str) -> str:
    return " – ".join(TX[lang]["other"] if c == "other" else crop_name(c, lang) for c in steps)


def _name(steps: list[str], covers: list[bool], lang: str) -> str:
    return _label(steps, lang) + (TX[lang]["cover_suffix"] if any(covers) else "")


# --------------------------------------------------------------------------- the entry point

def plan_rotations(ctx: FieldContext, a: Assets, *, priorities: dict | None = None, farmer_input: dict | None = None,
                   lang: str = "uk", n_strategies: int | None = None, stress: StressSignal | None = None,
                   settings: dict | None = None, forced_cycle: list[str] | None = None) -> dict:
    """ctx already carries the scenario (temperature / rain shift) in its climate. returns strategies in the contract format.
    farmer_input: irrigated, has_livestock, excluded_crops (never offered in an alternative). forced_cycle: the rotation
    the farmer states, it replaces the detection."""
    cfg = settings or load_settings()
    t = TX[lang]
    fi = farmer_input or {}
    weights = {k: (priorities or {}).get(k, 0.5) for k in PRIORITY_KEYS}
    n_alt = n_strategies or cfg["n_strategies"]
    h = cfg["horizon_years"]

    if forced_cycle:
        last = (ctx.history_rich or ctx.history).get(ctx.target_year - 1)
        det = forced_rotation(forced_cycle, last, h)
    else:
        det = detect_rotation(ctx.history_rich or ctx.history, ctx.target_year, h, cfg["rotation_detection"])
    excluded = set(fi.get("excluded_crops") or [])
    pl = Planner(ctx, a, cfg, irrigated=fi.get("irrigated"), has_livestock=fi.get("has_livestock"), lang=lang, stress=stress)

    pl.cover_slots(det.steps)    # also records why a cover crop is not allowed here, if so
    nothing_fits = all(v == 0 for v in pl.step(ctx.prev_crops[0], ctx.prev_crops[1], False)["scores"].values())

    # current rotation = the detected cycle continued
    cur_covers = [False] * h
    current = pl.variant(det.steps, cur_covers, weights)
    current["tag"] = "current"

    # all chains x (no cover / cover wherever it fits)
    variants = []
    for steps in itertools.product([c for c in pl.main if c not in excluded], repeat=h):
        steps = list(steps)
        score, _ = pl.chain(steps)
        if score <= 0:
            continue
        slots = pl.cover_slots(steps) if cfg["cover"]["crop"] not in excluded else [False] * h
        for covers in ([False] * h, slots) if any(slots) else ([False] * h,):
            v = pl.variant(steps, covers, weights)
            v["tag"] = logic_tag(steps, covers, det.steps, a)
            variants.append(v)
    alts = pick_alternatives(variants, current, n_alt, cfg["min_fit"], cfg["max_loss_vs_current"], cfg["logic_order"])

    # ---- output
    cur_scores = _scores(current)
    strategies, details = [], {}
    sources_used = {"csb", "power", "ssurgo"}
    gaps = _data_gaps(ctx, pl, fi, t, stress)
    if nothing_fits:
        gaps.insert(0, t["gap_nothing_fits"])

    def build(v: dict, sid: str, is_current: bool) -> dict:
        r, sc = v["agro"], _scores(v)
        c0, r0 = current["agro"], current["agro"]
        evidence, benefits, risks = [], [], []
        if is_current:
            if det.window == 0:
                why = t["why_farmer"].format(h=h)
            else:
                why = (t["why_current"].format(y0=det.years_used[0], y1=det.years_used[1], p=det.period, agree=det.agreement, h=h)
                       if det.clean else t["why_current_weak"].format(y0=det.years_used[0], y1=det.years_used[1], p=det.period))
            benefits = [t["ben_none"]]
            if r.pest_pairs:
                risks.append(t["risk_repeat"])
        else:
            why = t["logic"][v["tag"]] + " " + t["why_numbers"].format(
                b0=r0.bare_days, b1=r.bare_days, e0=r0.erosion_t_ha, e1=r.erosion_t_ha, n0=r0.n_net, n1=r.n_net)
            evidence = [
                {"text": t["ev_bare"].format(a=r0.bare_days, b=r.bare_days), "source_ids": ["csb"]},
                {"text": t["ev_erosion"].format(a=r0.erosion_t_ha, b=r.erosion_t_ha, p=ctx.precip_annual, k=ctx.soil["kw_factor"], s=ctx.slope_pct),
                 "source_ids": ["power", "ssurgo", "nasadem"] if ctx.slope_source == "nasadem" else ["power", "ssurgo"]},
                {"text": t["ev_water"].format(a=r0.water_use_mm, b=r.water_use_mm, p=ctx.precip_annual), "source_ids": ["power"]},
                {"text": t["ev_nitrogen"].format(a=r0.n_net, b=r.n_net, f=r.n_fixed), "source_ids": ["csb"]},
            ]
            if ctx.scenario != (0.0, 0.0):
                evidence.append({"text": t["ev_scenario"].format(t=ctx.scenario[0], p=ctx.scenario[1], wb=ctx.climate_norm["water_balance_grow"]),
                                 "source_ids": ["power"]})
            if stress and stress.active:
                evidence.append({"text": t["ev_stress"].format(pct=stress.pct_below, z=stress.z), "source_ids": ["landsat_ndvi"]})
                sources_used.add("landsat_ndvi")
            if r.bare_days < r0.bare_days * 0.9:
                benefits.append(t["ben_bare"].format(x=100 * (1 - r.bare_days / r0.bare_days)))
            if r.erosion_t_ha < r0.erosion_t_ha * 0.9:
                benefits.append(t["ben_erosion"].format(x=100 * (1 - r.erosion_t_ha / r0.erosion_t_ha)))
            if r.n_net - r0.n_net >= 10:
                benefits.append(t["ben_nitrogen"].format(x=r.n_net - r0.n_net))
            if r.pest_break and not r0.pest_break:
                benefits.append(t["ben_pest"])
            if sc["income"] - cur_scores["income"] >= 2:
                benefits.append(t["ben_income"].format(x=sc["income"] - cur_scores["income"]))
            if r.water_use_mm < r0.water_use_mm - 15:
                benefits.append(t["ben_water"].format(x=r0.water_use_mm - r.water_use_mm))
            if r.water_use_mm > r0.water_use_mm + 15:
                risks.append(t["risk_water"].format(x=r.water_use_mm - r0.water_use_mm))
            if sc["income"] - cur_scores["income"] <= -3:
                risks.append(t["risk_income"].format(x=cur_scores["income"] - sc["income"]))
            if v["fit"] < 60:
                risks.append(t["risk_fit"])
            if r.pest_pairs:
                risks.append(t["risk_repeat"])
            if any(v["covers"]):
                risks.append(t["risk_cover"])
            if "alfalfa" in v["steps"] and fi.get("has_livestock") is not True:
                risks.append(t["risk_forage"])
            if stress and stress.active and ctx.prev_crops[0] in v["steps"][:1]:
                risks.append(t["risk_stress"].format(pct=stress.pct_below))
            benefits = benefits or [t["ben_none"]]
        check = t["check"].get(v["tag"], [])
        conf = det.confidence if is_current else float(np.clip(min(det.confidence + 0.05, 0.3 + 0.6 * v["fit"] / 100), 0.25, 0.9))
        seq = []
        for i, (crop, cov) in enumerate(zip(v["steps"], v["covers"]), start=1):
            for part in crop.split("+"):          # a double crop is two main crops in the same year
                seq.append({"year": i, "season": "main", "crop": part})
            if cov:
                seq.append({"year": i, "season": "cover", "crop": cfg["cover"]["crop"]})
        details[sid] = {"steps": list(v["steps"]), "covers": list(v["covers"]), "logic": v["tag"], "fit": round(v["fit"], 1), "chain_score": v["chain_score"], "n_balance_kg_ha_yr": round(r.n_net, 1),
                        "pest_cycle_break": r.pest_break, "repeated_pairs": r.pest_pairs, "water_ratio": round(r.water_ratio, 2),
                        "r_factor": round(r.r_factor), "cover_after_years": [i + 1 for i, c in enumerate(v["covers"]) if c]}
        return {
            "id": sid, "is_current": is_current,
            "name": t["current"].format(name=_label(det.cycle, lang)) if is_current
                    else _name(v["steps"], v["covers"], lang),
            "sequence": seq, "scores": sc,
            "delta_vs_current": None if is_current else {k: sc[k] - cur_scores[k] for k in sc},
            "metrics": {"water_use_mm_yr": round(r.water_use_mm), "n_fixed_kg_ha_yr": round(r.n_fixed),
                        "bare_days_yr": round(r.bare_days), "erosion_t_ha_yr": round(r.erosion_t_ha, 1)},
            "why": why, "evidence": evidence, "benefits": benefits, "risks": risks,
            "data_gaps": gaps, "check_with_agronomist": check, "confidence": round(conf, 2),
        }

    strategies.append(build(current, "current", True))
    for i, v in enumerate(alts, start=1):
        strategies.append(build(v, f"s{i}", False))

    return {
        "field_id": ctx.field_id, "language": lang,
        "current_rotation": {"sequence": det.cycle, "label": _label(det.cycle, lang),
                             "confidence": round(det.confidence, 2), "years_used": det.years_used, "source": "farmer_input" if det.window == 0 else "csb",
                             "agreement": round(det.agreement, 2), "window_years": det.window, "cycle_years": det.period, "clean": det.clean},
        "strategies": strategies, "details": details,
        "stress": None if stress is None else {"active": stress.active, "reason": stress.reason, "z": stress.z, "pct_below": stress.pct_below,
                                                "crop": stress.crop, "months": stress.months, "intensity": stress.intensity},
        "scenario": {"temp_delta_c": ctx.scenario[0], "precip_change_pct": ctx.scenario[1]},
        "score_notes": {"income": "income_index: a relative 0-100 index of margin, not money"},
        "sources": [{"id": s[0], "name": s[1], "variable": s[2], "resolution": s[3], "period": s[4]} for s in SOURCES[lang]],
        "candidates_evaluated": len(variants), "alternatives_requested": n_alt,
    }


def _scores(v: dict) -> dict:
    out = {k: int(round(v["scores"][k])) for k in PRIORITY_KEYS}
    out["overall"] = int(round(v["overall"]))
    return out


def _data_gaps(ctx, pl: Planner, fi: dict, t: dict, stress) -> list[str]:
    gaps = []
    if fi.get("irrigated") is None and not ctx.irrigated:
        first = pl.step(ctx.prev_crops[0], ctx.prev_crops[1], False)["result"]
        # when water is short for some crops, the farmer is asked to say whether the field is irrigated: the answer changes the advice
        gaps.append(t["gap_irrigation_set"] if first.get("water_short") else t["gap_irrigation"])
    if fi.get("has_livestock") is None:
        gaps.append(t["gap_livestock"])
    gaps += ([] if ctx.slope_source == "nasadem" else [t["gap_slope"]]) + [t["gap_income"]]
    if stress is None or stress.reason == "no ndvi data":
        gaps.append(t["gap_stress"])
    if pl.cover_blocked:
        gaps.append(t["gap_cover_blocked"].format(why="; ".join(pl.cover_blocked[:1])))
    return gaps
