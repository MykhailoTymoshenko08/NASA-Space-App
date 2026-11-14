"""Serve XYZ vector tiles out of a prebuilt PMTiles archive (built by tippecanoe).

PMTiles spec: https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md
Python reader: https://github.com/protomaps/PMTiles/tree/main/python
"""

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
