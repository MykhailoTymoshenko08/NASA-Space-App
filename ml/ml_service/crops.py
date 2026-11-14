"""Crop catalog with the agronomic constants used by the mock engine.

Values are rough Corn Belt numbers - good enough for plausible demo output, not calibrated.
`curve` is the monthly canopy cover (jan..dec, 0-1) of a typical season; `residue` is the
winter ground cover left by the crop (used as a floor outside the growing season).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Crop:
    slug: str
    cdl_code: int
    name_en: str
    name_uk: str
    type: str  # cash | legume | cover | perennial
    water_mm: float  # seasonal crop water use (Kc x ET0); for covers - extra use
    n_fix: float  # kg/ha/yr biologically fixed
    n_net: float  # kg/ha/yr net n balance left for the next crop (negative = removal)
    income: float  # 0-100 relative margin index; for covers - seed/termination cost
    c_factor: float  # rusle C; for covers - multiplier applied to the main crop C
    heat_sens: float  # 0-1 income sensitivity to warming
    drought_sens: float  # 0-1 income sensitivity to less rain
    residue: float
    curve: tuple[float, ...]

    @property
    def is_cover(self) -> bool:
        return self.type == "cover"

    @property
    def is_legume(self) -> bool:
        return self.n_fix > 0


_CROPS = [
    Crop("corn", 1, "Corn", "Кукурудза", "cash", 600, 0, -120, 82, 0.38, 1.0, 1.0, 0.12,
         (0, 0, 0, 0.05, 0.15, 0.4, 0.9, 1.0, 0.9, 0.4, 0, 0)),
    Crop("soybean", 5, "Soybeans", "Соя", "legume", 480, 60, 30, 74, 0.32, 0.6, 0.7, 0.06,
         (0, 0, 0, 0, 0.05, 0.2, 0.7, 1.0, 0.9, 0.2, 0, 0)),
    Crop("sorghum", 4, "Sorghum", "Сорго", "cash", 450, 0, -90, 64, 0.33, 0.1, 0.3, 0.12,
         (0, 0, 0, 0, 0.05, 0.2, 0.6, 0.95, 0.95, 0.5, 0, 0)),
    Crop("winter_wheat", 24, "Winter wheat", "Озима пшениця", "cash", 420, 0, -60, 60, 0.20, 0.2, 0.5, 0.12,
         (0.25, 0.25, 0.35, 0.6, 0.9, 0.95, 0.3, 0.05, 0.05, 0.2, 0.4, 0.3)),
    Crop("oats", 28, "Oats", "Овес", "cash", 380, 0, -50, 48, 0.22, 0.4, 0.6, 0.08,
         (0, 0, 0, 0, 0.3, 0.8, 0.9, 0.2, 0, 0, 0, 0)),
    Crop("alfalfa", 36, "Alfalfa", "Люцерна", "perennial", 700, 150, 120, 58, 0.02, 0.4, 0.5, 0.0,
         (0.2, 0.2, 0.3, 0.6, 0.9, 1.0, 1.0, 1.0, 0.95, 0.7, 0.4, 0.25)),
    # cover crops: water_mm = extra use, income = cost, c_factor = multiplier on main crop C
    Crop("cereal_rye", 27, "Cereal rye", "Жито (покривна)", "cover", 60, 0, 10, -3, 0.5, 0, 0, 0.0,
         (0.2, 0.2, 0.25, 0.5, 0.75, 0.2, 0, 0, 0, 0.1, 0.25, 0.25)),
    Crop("hairy_vetch", 224, "Hairy vetch", "Вика волосиста (покривна)", "cover", 45, 70, 40, -4, 0.6, 0, 0, 0.0,
         (0.12, 0.12, 0.2, 0.5, 0.8, 0.3, 0, 0, 0, 0.1, 0.2, 0.15)),
    Crop("clover", 58, "Clover", "Конюшина (покривна)", "cover", 40, 60, 35, -3, 0.6, 0, 0, 0.0,
         (0.1, 0.1, 0.2, 0.45, 0.7, 0.5, 0.3, 0.3, 0.3, 0.3, 0.2, 0.15)),
]

CATALOG: dict[str, Crop] = {c.slug: c for c in _CROPS}
BY_CDL: dict[int, Crop] = {c.cdl_code: c for c in _CROPS}


def get(slug: str) -> Crop | None:
    return CATALOG.get(slug)


def resolve(slug: str | None, cdl_code: int | None = None) -> Crop | None:
    """find a catalog crop by slug first, then by cdl code"""
    if slug and slug in CATALOG:
        return CATALOG[slug]
    if cdl_code is not None:
        return BY_CDL.get(cdl_code)
    return None
