"""NASA POWER daily data for a POWER grid cell, cached on disk (the same cache and cell keys as scripts/02_power_climate.py).

A field outside the precomputed region needs its cell. If the cell is not in the cache we try to download it within a
time budget; a request that cannot wait is answered with 503 DATA_UNAVAILABLE and the download goes on in the
background, so the retry finds the cell in the cache.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import requests

from .errors import data_unavailable

ROOT = Path(__file__).resolve().parent.parent
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN"]
LAT_STEP, LON_STEP = 0.5, 0.625
START, END = "20170101", "20251231"     # the years the model was trained on: normals must use the same ones
BUDGET_S = float(os.environ.get("ML_POWER_BUDGET_S", "8"))

_inflight: set[str] = set()
_lock = threading.Lock()


def cache_dir() -> Path:
    return Path(os.environ.get("ML_POWER_CACHE_DIR", ROOT / "data" / "features" / "power_cache"))


def snap_to_cell(lat: float, lon: float) -> tuple[float, float]:
    """center of the merra-2 cell containing the point (same rule as scripts/02_power_climate.py)"""
    return round(round(lat / LAT_STEP) * LAT_STEP, 4), round(round(lon / LON_STEP) * LON_STEP, 4)


def cell_key(lat: float, lon: float) -> str:
    return f"{lat:+08.3f}_{lon:+09.3f}"


def cell_path(lat: float, lon: float) -> Path:
    clat, clon = snap_to_cell(lat, lon)
    return cache_dir() / f"{cell_key(clat, clon)}.json"


def _download(clat: float, clon: float, timeout: float) -> None:
    query = {"parameters": ",".join(PARAMS), "community": "AG", "latitude": clat, "longitude": clon,
             "start": START, "end": END, "format": "JSON", "time-standard": "LST"}
    r = requests.get(POWER_URL, params=query, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    path = cache_dir() / f"{cell_key(clat, clon)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)                      # never leave a half-written cache file


def download_cell(clat: float, clon: float, retries: int = 5, timeout: float = 120) -> Path:
    """for batch jobs (scripts/09): download with retries and backoff; returns the cache path."""
    import time
    path = cache_dir() / f"{cell_key(clat, clon)}.json"
    if path.exists():
        return path
    for attempt in range(retries):
        try:
            _download(clat, clon, timeout)
            return path
        except Exception:
            time.sleep(2 ** attempt * 3)
    raise RuntimeError(f"power failed after {retries} attempts for {clat},{clon}")


def _background(clat: float, clon: float) -> None:
    key = cell_key(clat, clon)
    with _lock:
        if key in _inflight:
            return
        _inflight.add(key)

    def run():
        try:
            _download(clat, clon, timeout=180)
        except Exception:
            pass
        finally:
            with _lock:
                _inflight.discard(key)

    threading.Thread(target=run, daemon=True).start()


def ensure_cell(lat: float, lon: float, budget_s: float | None = None) -> tuple[Path, float, str]:
    """(path of the cell json, cell latitude, cell key). downloads within the budget or raises 503."""
    clat, clon = snap_to_cell(lat, lon)
    path = cell_path(lat, lon)
    if path.exists():
        return path, clat, cell_key(clat, clon)
    try:
        _download(clat, clon, timeout=BUDGET_S if budget_s is None else budget_s)
    except Exception as exc:               # timeout, network, rate limit: keep trying in the background
        _background(clat, clon)
        raise data_unavailable("Climate data for this field is not prepared yet; it is being downloaded, retry in a minute.",
                               cell=cell_key(clat, clon), reason=exc.__class__.__name__, retry_after_s=60) from exc
    return path, clat, cell_key(clat, clon)
