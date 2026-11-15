"""Special CDL codes for reading a field's history as a rotation (NOT used by the model, whose classes stay the same).

61 = fallow. Double crops are two crops in one year; the CDL legend names both. NOTE: the range 225-254 also holds
codes that are not double crops (e.g. 227 lettuce, 229 pumpkins, 242-250 berries and vegetables), so only the
real double-crop codes are listed here, with the two crops in the order they are grown.
Crops that are not candidates stay "other".
"""
from __future__ import annotations

FALLOW_CODE = 61

DOUBLE_CROPS: dict[int, tuple[str, str]] = {   # code -> (first crop, second crop); "other" = not a candidate
    26: ("winter_wheat", "soybean"),    # Dbl Crop WinWht/Soybeans
    225: ("winter_wheat", "corn"),      # Dbl Crop WinWht/Corn
    226: ("oats", "corn"),              # Dbl Crop Oats/Corn
    228: ("other", "corn"),             # Dbl Crop Triticale/Corn
    230: ("other", "other"),            # Dbl Crop Lettuce/Durum Wht
    231: ("other", "other"),            # Dbl Crop Lettuce/Cantaloupe
    232: ("other", "other"),            # Dbl Crop Lettuce/Cotton
    233: ("other", "barley"),           # Dbl Crop Lettuce/Barley
    234: ("other", "sorghum"),          # Dbl Crop Durum Wht/Sorghum
    235: ("barley", "sorghum"),         # Dbl Crop Barley/Sorghum
    236: ("winter_wheat", "sorghum"),   # Dbl Crop WinWht/Sorghum
    237: ("barley", "corn"),            # Dbl Crop Barley/Corn
    238: ("winter_wheat", "other"),     # Dbl Crop WinWht/Cotton
    239: ("soybean", "other"),          # Dbl Crop Soybeans/Cotton
    240: ("soybean", "oats"),           # Dbl Crop Soybeans/Oats
    241: ("corn", "soybean"),           # Dbl Crop Corn/Soybeans
    254: ("barley", "soybean"),         # Dbl Crop Barley/Soybeans
}


def history_token(code: int, cdl_to_slug: dict) -> str:
    """what grew in a year, for rotation detection: a candidate slug, "fallow", a double crop "a+b", or "other"."""
    code = int(code)
    if code == FALLOW_CODE:
        return "fallow"
    if code in DOUBLE_CROPS:
        first, second = DOUBLE_CROPS[code]
        return f"{first}+{second}"
    return cdl_to_slug.get(code, "other")


def components(token: str) -> list[str]:
    return token.split("+")


def first_component(token: str) -> str:
    return components(token)[0]


def last_component(token: str) -> str:
    """the crop grown last in that year: what the next year follows"""
    return components(token)[-1]


# CDL codes of land that is not cropland: open water, developed, barren, forest, shrub, grass / pasture, wetlands
NON_CROP_CODES = {111, 112, 121, 122, 123, 124, 131, 141, 142, 143, 152, 176, 190, 195}


def noncrop_note(codes: dict[int, int], last_years: int = 5, min_years: int = 2) -> str | None:
    """a warning when the recent history is mostly not cropland (a lawn, a pasture, a lot at the edge of a town ...):
    a crop plan for such a parcel is a guess. codes: year -> CDL code."""
    recent = sorted(codes)[-last_years:]
    bad = [y for y in recent if int(codes[y]) in NON_CROP_CODES]
    if len(bad) < min_years:
        return None
    return (f"the CDL shows land that is not cropland in {len(bad)} of the last {len(recent)} years ({', '.join(str(y) for y in bad)}: "
            f"grass, pasture or developed): check that this is a working field before relying on the plan")
