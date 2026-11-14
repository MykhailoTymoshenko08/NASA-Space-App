"""Candidate rotations and the simple agro calculator behind the 5 scores.

Scores are 0-100, higher = better for the farmer. This is the mock stand-in for the future
model + calculator (Kc x ET0 water use, N fixation, bare days, simplified RUSLE).
"""
from dataclasses import dataclass

import numpy as np

from . import crops as crop_db
from .climate import Context, P_NORM, Rotation, TEMP_ET0_PER_C, bare_days

SCORE_KEYS = ("water", "soil_health", "nitrogen", "erosion", "income")


@dataclass
class Evaluation:
    scores: dict[str, float]  # the 5 unweighted scores, unrounded
    water_use: float
    n_fixed: float
    bare_days: int
    erosion: float


@dataclass
class Candidate:
    kind: str
    rotation: Rotation
    complexity: int  # number of changes vs current, lowers confidence


def mains_of(rotation: Rotation) -> list[str]:
    return [m for m, _ in rotation]


def signature(rotation: Rotation) -> tuple:
    return tuple((m, tuple(sorted(c))) for m, c in rotation)


def plain(mains: list[str]) -> Rotation:
    return [(m, ()) for m in mains]


def build_candidates(current_mains: list[str], excluded: set[str]) -> list[Candidate]:
    """alternatives derived from the current rotation; excluded crops are filtered out"""
    cur = plain(current_mains)
    raw: list[Candidate] = []

    # cover crops go on annual years only - a perennial stand is already covered
    def with_cover(covers_for) -> Rotation:
        return [(m, tuple(covers_for(m)) if not crop_db.CATALOG[m].type == "perennial" else ()) for m in current_mains]

    raw.append(Candidate("cover_rye", with_cover(lambda m: ["cereal_rye"]), 1))
    raw.append(Candidate("cover_mix", with_cover(lambda m: ["cereal_rye", "hairy_vetch"]), 2))

    # legume: vetch on non-legume years, and a soybean year if the rotation has no legume at all
    legume_mains = list(current_mains)
    if not any(crop_db.CATALOG[m].is_legume for m in legume_mains):
        legume_mains.append("soybean")
    raw.append(Candidate(
        "legume",
        [(m, () if crop_db.CATALOG[m].is_legume or crop_db.CATALOG[m].type == "perennial" else ("hairy_vetch",))
         for m in legume_mains], 2))

    # drought-tolerant: corn -> sorghum, oats -> winter wheat
    swap = {"corn": "sorghum", "oats": "winter_wheat"}
    swapped = [swap.get(m, m) for m in current_mains]
    if swapped != current_mains:
        raw.append(Candidate("drought", plain(swapped), 1))

    # perennial phase: 3 years of alfalfa, then back to the first annual crop of the current rotation
    if "alfalfa" not in current_mains:
        back_to = next((m for m in current_mains if crop_db.CATALOG[m].type != "perennial"), "corn")
        raw.append(Candidate("perennial", plain(["alfalfa", "alfalfa", "alfalfa", back_to]), 3))

    # diversified 3-year with a small grain and clover after the wheat
    div = [("corn", ()), ("soybean", ()), ("winter_wheat", ("clover",))]
    raw.append(Candidate("diversified", div, 3))

    seen = {signature(cur)}
    out = []
    for c in raw:
        used = {x for m, covers in c.rotation for x in (m, *covers)}
        sig = signature(c.rotation)
        if used & excluded or sig in seen:
            continue
        seen.add(sig)
        out.append(c)
    return out


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return float(min(hi, max(lo, x)))


def evaluate(rotation: Rotation, ctx: Context) -> Evaluation:
    crops = {slug: crop_db.CATALOG[slug] for m, covers in rotation for slug in (m, *covers)}
    n = len(rotation)
    et_scale = 1 + TEMP_ET0_PER_C * ctx.temp_delta

    water_use = n_fixed = n_net = income = c_mean = 0.0
    for main, covers in rotation:
        m = crops[main]
        cv = [crops[c] for c in covers]
        water_use += (m.water_mm + sum(c.water_mm for c in cv)) * et_scale
        n_fixed += m.n_fix + sum(c.n_fix for c in cv)
        n_net += m.n_net + sum(c.n_net for c in cv)

        inc = m.income + sum(c.income for c in cv)  # cover income is a (negative) cost
        inc -= m.heat_sens * 4.0 * max(0.0, ctx.temp_delta)  # warming hurts heat-sensitive crops
        inc -= m.drought_sens * 0.25 * max(0.0, -ctx.precip_pct)  # so does less rain
        if main == "alfalfa" and ctx.has_livestock is True:
            inc += 15
        elif main == "alfalfa" and ctx.has_livestock is False:
            inc -= 10
        income += inc

        c_mean += m.c_factor * (min(c.c_factor for c in cv) if cv else 1.0)

    water_use /= n
    n_fixed /= n
    n_net /= n
    income /= n
    c_mean /= n

    # water: usable rain + half of the plant-available water in a 1 m root zone vs crop demand
    supply = sum(P_NORM) * ctx.climate[0] * (1 + ctx.precip_pct / 100) * 0.6 + ctx.awc * 500
    if ctx.irrigated:
        supply += 250
    water = _clip(100 * (supply / water_use - 0.7) / 0.9)

    # simplified rusle: A = R*K*LS*C, folded into one calibrated factor
    k = float(np.clip(0.34 - 0.025 * ctx.om_pct, 0.15, 0.40))
    erosion = 55.0 * k * (0.5 + 0.35 * ctx.slope_pct) * c_mean
    erosion_score = _clip(100 * (1 - erosion / 10.0))

    mains = [m for m, _ in rotation]
    diversity = min(len(set(mains)), 3) * 8
    legume_frac = sum(crops[m].is_legume for m in mains) / n
    cover_frac = sum(bool(c) for _, c in rotation) / n
    perennial_frac = sum(crops[m].type == "perennial" for m in mains) / n
    soil = _clip(12 + diversity + 8 * legume_frac + 28 * cover_frac + 35 * perennial_frac + min(15.0, 3 * ctx.om_pct))

    nitrogen = _clip(60 + 0.3 * n_net)

    return Evaluation(
        scores={"water": water, "soil_health": soil, "nitrogen": nitrogen,
                "erosion": erosion_score, "income": _clip(income)},
        water_use=water_use,
        n_fixed=n_fixed,
        bare_days=bare_days(rotation),
        erosion=erosion,
    )


def overall(scores: dict[str, float], weights: dict[str, float]) -> float:
    """priority-weighted mean; all-zero priorities fall back to equal weights"""
    total = sum(weights.values())
    if total <= 0:
        weights, total = {k: 1.0 for k in SCORE_KEYS}, float(len(SCORE_KEYS))
    return sum(scores[k] * weights[k] for k in SCORE_KEYS) / total


def detect_rotation(crops_by_year: list[str]) -> tuple[list[str], float]:
    """find the shortest repeating cycle (1-3 years) in the crop history, with a confidence"""
    n = len(crops_by_year)
    for p in (1, 2, 3):
        if n >= max(3, 2 * p) and all(crops_by_year[i] == crops_by_year[i + p] for i in range(n - p)):
            return crops_by_year[:p], min(0.95, 0.55 + 0.05 * n)
    # no clean cycle: use the last two distinct crops as a weak guess
    tail = []
    for c in reversed(crops_by_year):
        if c not in tail:
            tail.append(c)
        if len(tail) == 2:
            break
    return list(reversed(tail)), 0.45
