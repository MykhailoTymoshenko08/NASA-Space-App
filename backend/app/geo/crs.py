"""CRS helpers. Distances, buffers and areas are computed in EPSG:5070 (CONUS Albers, metres)."""

import numpy as np
import shapely
from pyproj import Transformer

# always_xy=True: input/output order is (lon, lat) / (x, y). Never (lat, lon).
_TO_5070 = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
_TO_4326 = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True)

# CONUS bbox from the backend spec: [west, south, east, north].
CONUS_BBOX = (-125.0, 24.4, -66.9, 49.6)


def lonlat_to_5070(lon: float, lat: float) -> tuple[float, float]:
    return _TO_5070.transform(lon, lat)


def xy_to_lonlat(x: float, y: float) -> tuple[float, float]:
    return _TO_4326.transform(x, y)


def _apply(t: Transformer, geoms):
    return shapely.transform(
        np.asarray(geoms), lambda c: np.column_stack(t.transform(c[:, 0], c[:, 1]))
    )


def to_5070(geoms):
    return _apply(_TO_5070, geoms)


def to_4326(geoms):
    return _apply(_TO_4326, geoms)


def in_conus_bbox(lat: float, lon: float) -> bool:
    w, s, e, n = CONUS_BBOX
    return w <= lon <= e and s <= lat <= n
