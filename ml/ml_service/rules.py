"""Evaluates the agronomic rules of config/crop_rules.yaml for one crop in one field.

A rule can: block the crop (hard_block), or scale its score (penalty / bonus, optionally on a linear ramp).
Points are on a 0-100 scale, so a penalty of 25 points is a multiplier of 0.75 and a bonus of 5 points is 1.05.
A rule whose variables are unknown (no SMAP yet, no TWI yet) is not evaluated and is reported as a data gap.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

_OPS = {
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b, "in": lambda a, b: a in b, "contains": lambda a, b: b in a,
}


@dataclass
class RuleResult:
    rule_id: str
    kind: str            # block | penalty | bonus
    multiplier: float    # 0 for a block
    explanation: dict    # {"en": ..., "uk": ...}


def load_rules(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


def _known(v) -> bool:
    return v is not None and not (isinstance(v, float) and np.isnan(v))


def applies(rule: dict, slug: str, crops: dict) -> bool:
    if slug not in crops:
        return False
    ap = rule["applies_to"]
    listed = ap.get("crops", [])
    if listed == "all" or slug in listed:
        return True
    return bool(set(ap.get("tags", [])) & set(crops[slug].get("tags", [])))


def rule_variables(rule: dict) -> list[str]:
    """every variable a rule needs (conditions and ramp)"""
    names = [c["var"] for c in rule.get("when", [])]
    ramp = rule["action"].get("ramp")
    if ramp:
        names.append(ramp["var"])
    return names


def evaluate_crop(slug: str, variables: dict, cfg: dict, skip_ids: set[str] = frozenset(),
                  skip_var_prefixes: tuple[str, ...] = ()) -> tuple[list[RuleResult], list[str]]:
    """returns (rules that fired, ids of rules that could not be evaluated because data is missing).
    skip_ids: rules handled elsewhere. skip_var_prefixes: rules that use these variables are ignored (irrigation)."""
    crops = cfg["crops"]
    fired, unknown = [], []
    for rule in cfg["rules"]:
        if rule["id"] in skip_ids or not applies(rule, slug, crops):
            continue
        names = rule_variables(rule)
        if any(n.startswith(skip_var_prefixes) for n in names):  # empty tuple never matches
            continue

        ok = True
        missing = False
        for cond in rule.get("when", []):
            value = variables.get(cond["var"])
            limit = cond.get("value")
            if "value_ref" in cond:  # e.g. crop.gdd_to_maturity
                limit = crops[slug].get(cond["value_ref"].split(".", 1)[1])
                if limit is None:   # crop has no such value (perennial, cover): the rule does not apply
                    ok = False
                    break
            if not _known(value):
                missing = True
                break
            if not _OPS[cond["op"]](value, limit):
                ok = False
                break
        if missing:
            unknown.append(rule["id"])
            continue
        if not ok:
            continue

        action = rule["action"]
        frac = 1.0
        ramp = action.get("ramp")
        if ramp:
            x = variables.get(ramp["var"])
            if not _known(x):
                unknown.append(rule["id"])
                continue
            frac = float(np.clip((x - ramp["zero_at"]) / (ramp["full_at"] - ramp["zero_at"]), 0.0, 1.0))
            if frac == 0.0:
                continue
        kind = action["type"]
        if kind == "hard_block":
            fired.append(RuleResult(rule["id"], "block", 0.0, rule["explanation"]))
        else:
            sign = -1.0 if kind == "penalty" else 1.0
            fired.append(RuleResult(rule["id"], kind, 1.0 + sign * action["points"] * frac / 100.0, rule["explanation"]))
    return fired, unknown
