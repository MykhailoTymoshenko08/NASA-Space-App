"""Helpers shared by the data preparation scripts."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402

USER_AGENT = "field-shift-data-prep/0.1"

# CONUS = 48 states + DC. Excludes AK (02), HI (15) and territories (60+).
NON_CONUS_STATE_FIPS = {"02", "15"}


def is_conus_state(fips: str) -> bool:
    return fips not in NON_CONUS_STATE_FIPS and int(fips) < 60


def data_dir() -> Path:
    d = get_settings().data_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def http_client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True
    )


def require_tippecanoe() -> str:
    exe = shutil.which("tippecanoe")
    if not exe:
        sys.exit(
            "tippecanoe not found. Install it first (README > Setup):\n"
            "  Arch:   yay -S tippecanoe\n"
            "  macOS:  brew install tippecanoe\n"
            "  Debian/Ubuntu: build from https://github.com/felt/tippecanoe"
        )
    return exe


def run_tippecanoe(args: list[str]) -> None:
    exe = require_tippecanoe()
    cmd = [exe, "--force", "--quiet", *args]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    tmp.replace(path)
