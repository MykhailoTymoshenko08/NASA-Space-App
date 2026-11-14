"""
step 11 - collect what the Docker image needs into deploy/data (the image has no access to data/).

  data/precomputed/*.parquet                      precomputed demo counties
  data/features/power_cache/<cell>.json          ONLY the POWER cells those counties use (scenario sliders recompute from daily data)
  data/lina/{ndvi_monthly.csv,derived.parquet}   when Lina's files are installed (--no-ndvi leaves the big NDVI file out)

usage: python scripts/11_prepare_deploy.py [--out deploy/data] [--no-ndvi]
then:  docker compose build
"""
import argparse
import shutil
from pathlib import Path

import pandas as pd


def size(p: Path) -> str:
    total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size
    return f"{total / 1e6:.1f} MB"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="deploy/data")
    ap.add_argument("--no-ndvi", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "precomputed").mkdir(parents=True)
    (out / "features" / "power_cache").mkdir(parents=True)

    files = sorted(Path("data/precomputed").glob("*.parquet"))
    if not files:
        raise SystemExit("no data/precomputed/*.parquet: run scripts/09_precompute_region.py first")
    cells = set()
    for f in files:
        shutil.copy2(f, out / "precomputed" / f.name)
        cells |= set(pd.read_parquet(f, columns=["cell"])["cell"])
        print(f"  {f.name}: {len(pd.read_parquet(f, columns=['field_id'])):,} fields")
    for c in sorted(cells):
        shutil.copy2(Path("data/features/power_cache") / f"{c}.json", out / "features" / "power_cache" / f"{c}.json")
    print(f"  {len(cells)} POWER cells")

    lina = Path("data/lina")
    for name in ("derived.parquet", "ndvi_monthly.csv"):
        if (lina / name).exists() and not (args.no_ndvi and name == "ndvi_monthly.csv"):
            (out / "lina").mkdir(exist_ok=True)
            shutil.copy2(lina / name, out / "lina" / name)
            print(f"  lina/{name}")
    print(f"deploy data: {size(out)} in {out}")


if __name__ == "__main__":
    main()
