"""Serve XYZ vector tiles out of a prebuilt PMTiles archive (built by tippecanoe).

PMTiles spec: https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md
Python reader: https://github.com/protomaps/PMTiles/tree/main/python
"""

import math
import threading
from functools import lru_cache
from pathlib import Path

from pmtiles.reader import MmapSource, Reader
from pmtiles.tile import Compression, TileType


class TileSource:
    def __init__(self, path: Path):
        self.path = path
        self._f = path.open("rb")
        self._reader = Reader(MmapSource(self._f))
        h = self._reader.header()
        if h["tile_type"] != TileType.MVT:
            raise ValueError(f"{path} does not contain MVT tiles")
        self.compression: Compression = h["tile_compression"]
        self.min_zoom: int = h["min_zoom"]
        self.max_zoom: int = h["max_zoom"]
        self.bounds = (
            h["min_lon_e7"] / 1e7,
            h["min_lat_e7"] / 1e7,
            h["max_lon_e7"] / 1e7,
            h["max_lat_e7"] / 1e7,
        )
        self._lock = threading.Lock()
        self._get = lru_cache(maxsize=4096)(self._get_uncached)

    def _get_uncached(self, z: int, x: int, y: int) -> bytes | None:
        with self._lock:
            data = self._reader.get(z, x, y)
        return bytes(data) if data else None

    def get(self, z: int, x: int, y: int) -> bytes | None:
        return self._get(z, x, y)

    @property
    def content_encoding(self) -> str | None:
        return {Compression.GZIP: "gzip", Compression.BROTLI: "br", Compression.ZSTD: "zstd"}.get(
            self.compression
        )

    def close(self) -> None:
        self._f.close()


def valid_tile(z: int, x: int, y: int) -> bool:
    n = 1 << z
    return 0 <= x < n and 0 <= y < n


def tile_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """[west, south, east, north] of an XYZ (slippy map) tile in degrees."""
    n = 1 << z

    def lon(xx: int) -> float:
        return xx / n * 360.0 - 180.0

    def lat(yy: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))

    return lon(x), lat(y + 1), lon(x + 1), lat(y)


def bbox_intersects(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]
