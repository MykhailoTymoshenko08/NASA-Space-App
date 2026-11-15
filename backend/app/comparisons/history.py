"""Crop history as a renter reads it: what was grown, how often, and whether corn followed corn."""

from collections.abc import Sequence
from typing import Literal

from app.models import CropHistorySummary

PATTERN_WINDOW = 4  # the latest years that decide the rotation pattern
CONTINUOUS_YEARS = 3  # the same crop this many years in a row, up to the latest year, is continuous
PATTERN_LABELS = {
    "corn_soybean": "Corn and soybeans in turn",
    "continuous_corn": "Corn after corn",
    "continuous_soybean": "Soybeans after soybeans",
    "mixed": "Mixed crops",
    "unknown": "Not enough years on record",
}


def crop_kind(name: str | None) -> Literal["corn", "soybean", "winter_wheat", "other"]:
    """CSB/CDL names ("Corn", "Soybeans", "Winter Wheat") or farmer text. Double crops count as other."""
    n = (name or "").strip().lower().replace("_", " ")
    if n == "corn":
        return "corn"
    if n in {"soybeans", "soybean"}:
        return "soybean"
    if n == "winter wheat":
        return "winter_wheat"
    return "other"


def summarize_history(
    history: Sequence[tuple[int, str]], source: Literal["farmer", "usda_csb", "none"],
) -> CropHistorySummary:
    """`history`: (year, crop) pairs in any order. Empty history gives `source: none` and zero counts."""
    rows = sorted(((int(y), c) for y, c in history if c), key=lambda r: -r[0])
    if not rows:
        return CropHistorySummary(
            source="none", years_recorded=0, first_year=None, latest_year=None, latest_crop=None,
            corn_years=0, soybean_years=0, other_years=0, distinct_crops=0, corn_in_a_row=0,
            pattern="unknown",
        )
    kinds = [crop_kind(c) for _, c in rows]

    def run(kind: str) -> int:
        n = 0
        while n < len(kinds) and kinds[n] == kind:
            n += 1
        return n

    corn_run = run("corn")
    window = kinds[:PATTERN_WINDOW]
    pattern: Literal["corn_soybean", "continuous_corn", "continuous_soybean", "mixed", "unknown"]
    if len(window) < 2:
        pattern = "unknown"
    elif corn_run >= CONTINUOUS_YEARS or all(k == "corn" for k in window):
        pattern = "continuous_corn"
    elif run("soybean") >= CONTINUOUS_YEARS or all(k == "soybean" for k in window):
        pattern = "continuous_soybean"
    elif set(window) <= {"corn", "soybean"} and all(a != b for a, b in zip(window, window[1:], strict=False)):
        pattern = "corn_soybean"
    else:
        pattern = "mixed"
    return CropHistorySummary(
        source=source, years_recorded=len(rows), first_year=rows[-1][0], latest_year=rows[0][0],
        latest_crop=rows[0][1], corn_years=kinds.count("corn"), soybean_years=kinds.count("soybean"),
        other_years=len(kinds) - kinds.count("corn") - kinds.count("soybean"),
        distinct_crops=len({c.strip().lower() for _, c in rows}), corn_in_a_row=corn_run, pattern=pattern,
    )
