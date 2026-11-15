"""Farmer wording for the ML service's free text in the PDF report.

The ML service writes its notes for developers ("set irrigated=true", "RUSLE: K=0.05", "No NDVI from Lina").
The report rewrites the known phrases (ml_service/rotations.py, real.py: English tables), removes model
details in brackets, and merges notes that say the same thing. Unknown text passes through with only the
generic clean-up, so a new ML message still prints, never disappears.
"""

import re
from dataclasses import dataclass

# (key, pattern, farmer text). The key merges a warning and a gap about the same thing; text None drops it.
_KNOWN: list[tuple[str, re.Pattern[str], str | None]] = [
    (
        "ndvi",
        re.compile(r"^No Landsat NDVI\b|^No NDVI\b"),
        "No recent satellite plant-health data, so last season's crop stress was not checked.",
    ),
    (
        "smap",
        re.compile(r"^No SMAP\b"),
        "No satellite soil-moisture data for this field, so the soil-moisture checks were skipped.",
    ),
    ("twi", re.compile(r"^No TWI\b"), "Low, wet spots in the field were not checked."),
    (
        "slope",
        re.compile(r"^No NASADEM\b|^Slope comes from SSURGO"),
        "Slope comes from the soil survey, not from elevation data.",
    ),
    (
        "income",
        re.compile(r"^Income is a relative"),
        "Income is a score from 0 to 100 that compares options. It is not a profit estimate.",
    ),
    (
        "irrigation",
        re.compile(r"^If the field is irrigated|^No field-level irrigation data"),
        "We do not know if this field is irrigated. If it is, the advice would change.",
    ),
    (
        "livestock",
        re.compile(r"^Livestock / forage demand"),
        "We do not know if you need hay or forage for livestock.",
    ),
    (
        "organic",
        re.compile(r"^organic soil", re.I),
        "Organic soil (over 20% organic matter): estimates for peat or muck soils are less reliable.",
    ),
    (
        "smap_near",
        re.compile(r"^SMAP \(9 km pixel\): the soil moisture of the nearest field"),
        "Soil moisture for this field is borrowed from the nearest field with satellite data, "
        "so the soil-moisture checks are approximate.",
    ),
    (
        "noncrop",
        re.compile(r"^the CDL shows land that is not cropland in (\d+) of the last (\d+) years \(([\d, ]+):"),
        r"Crop maps show grass, pasture or buildings here in \1 of the last \2 years (\3). "
        "Check that this is a working field before relying on the plan.",
    ),
    (
        "uncatalogued",
        re.compile(r"^crops not in the catalog were treated as 'other': (.+)$"),
        r"Some past years show land uses the model does not plan for (\1). They count as other land.",
    ),
    ("source", re.compile(r"^Field features (come from precomputed data|were computed on the fly)"), None),
]

_AGRONOMIST = re.compile(r"^Check with a local agronomist:\s*", re.I)
# Model details in brackets: formulas, parameters and method names, not the farmer's business.
_METHOD = re.compile(r"\s*\((?=[^()]*(?:[:=]|FAO|RUSLE|Kc|fixation))[^()]*\)")
_ARROW = re.compile(r"\s*->\s*")
# "Bare days 174->90 a year, erosion ..., nitrogen ... kg/ha." repeats the evidence lines word for word.
_NUMBERS = re.compile(r"\s*Bare days [-+\d.]+\s*->.*?kg/ha\.")
_BASELINE = re.compile(
    r"Baseline read from the CSB history (\d{4})-(\d{4}) \(cycle of (\d+) years?, [^)]*\), "
    r"continued for (\d+) years?\."
)
_NO_CYCLE = re.compile(
    r"No stable repeating cycle in (\d{4})-(\d{4}); "
    r"the closest one \((\d+) years?\) is used, low confidence\."
)


def clean(text: str) -> str:
    """Generic clean-up for any ML sentence: no method brackets, no ASCII arrows, single spaces."""
    text = _METHOD.sub("", text)
    text = _ARROW.sub(" to ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def summary(text: str) -> str:
    """A strategy's one-paragraph summary, without the numbers its evidence lines already give."""
    text = _NUMBERS.sub("", text)
    text = _BASELINE.sub(
        lambda m: (
            f"Your rotation as mapped in {m[1]} to {m[2]} (a {m[3]}-year cycle), "
            f"carried forward {m[4]} years."
        ),
        text,
    )
    text = _NO_CYCLE.sub(
        lambda m: f"No clear repeating cycle in {m[1]} to {m[2]}, so the closest {m[3]}-year cycle is used.",
        text,
    )
    return clean(text)


def _known(text: str) -> tuple[str | None, str | None]:
    """(key, farmer text) for a known phrase; (None, cleaned text) for anything else."""
    for key, pattern, plain in _KNOWN:
        if m := pattern.search(text):
            # Farmer texts may carry the ML message's numbers and names (\1, \2 ...).
            return key, m.expand(plain) if plain else None
    return None, clean(text)


@dataclass
class Notes:
    """A strategy's gaps, split for the card: what we do not know, and what to check locally."""

    unknown: list[str]
    check: list[str]


def gap_notes(gaps: list[str], said: set[str]) -> Notes:
    """Card notes, minus what "Keep in mind" already says (`said`: from `keep_in_mind_keys`)."""
    unknown: list[str] = []
    check: list[str] = []
    for g in gaps:
        if _AGRONOMIST.match(g):
            check.append(_AGRONOMIST.sub("", g).strip())
            continue
        key, plain = _known(g)
        if plain and (key or plain) not in said and plain not in unknown:
            unknown.append(plain)
    return Notes(unknown, check)


def shared_gaps(gap_lists: list[list[str]]) -> list[str]:
    """Gaps every strategy lists (about the field, not a strategy), in first-seen order. Needs two or more."""
    if len(gap_lists) < 2:
        return []
    common = set(gap_lists[0]).intersection(*map(set, gap_lists[1:]))
    return [g for g in dict.fromkeys(gap_lists[0]) if g in common and not _AGRONOMIST.match(g)]


def keep_in_mind(warnings: list[str], gaps: list[str]) -> tuple[list[str], set[str]]:
    """Report-level notes (warnings plus field-level gaps) in farmer words, each said once, and the keys
    of what they say, so the cards can leave those out."""
    out: list[str] = []
    seen: set[str] = set()
    for text in [*warnings, *gaps]:
        key, plain = _known(text)
        if plain is None or (key or plain) in seen:
            continue
        seen.add(key or plain)
        out.append(plain)
    return out, seen
