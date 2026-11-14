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
