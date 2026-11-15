"""
step 11 - collect what the Docker image needs into deploy/data (the image has no access to data/).

  data/precomputed/*.parquet                      precomputed demo counties
  data/features/power_cache/<cell>.json          ONLY the POWER cells those counties use (scenario sliders recompute from daily data)
  data/lina/derived.parquet                      NASADEM slope, SMAP dry-year share and its source
  data/lina/ndvi_monthly.csv -> ndvi_monthly.parquet   Lina's NDVI as a compact parquet (3M rows, ~15 MB; --no-ndvi leaves it out)

it only ADDS and REPLACES: nothing in the output folder is deleted, and a source that is not there (no POWER cache in a monorepo
checkout, no Lina files yet) is skipped with a message while what the folder already has stays as it is.

usage: python scripts/11_prepare_deploy.py [--out deploy/data] [--no-ndvi]
then:  docker compose build
"""
import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd

NDVI_DTYPES = {"field_id": "category", "year": "int16", "month": "int8", "ndvi_mean": "float32", "n_obs": "float32"}


def size(p: Path) -> str:
    total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size
    return f"{total / 1e6:.1f} MB"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="deploy/data")
    ap.add_argument("--no-ndvi", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    (out / "precomputed").mkdir(parents=True, exist_ok=True)
    (out / "features" / "power_cache").mkdir(parents=True, exist_ok=True)

    files = sorted(Path("data/precomputed").glob("*.parquet"))
    if not files:
        sys.exit("no data/precomputed/*.parquet: run scripts/09_precompute_region.py first (nothing was changed)")
    cells = set()
    for f in files:
        shutil.copy2(f, out / "precomputed" / f.name)
        cells |= set(pd.read_parquet(f, columns=["cell"])["cell"])
        print(f"  {f.name}: {len(pd.read_parquet(f, columns=['field_id'])):,} fields")

    cache, missing = Path("data/features/power_cache"), 0
    for c in sorted(cells):
        src, dst = cache / f"{c}.json", out / "features" / "power_cache" / f"{c}.json"
        if src.exists():
            shutil.copy2(src, dst)
        elif not dst.exists():
            missing += 1
    have = len(list((out / "features" / "power_cache").glob("*.json")))
    print(f"  POWER cells: {len(cells)} needed, {have} in {out}" + (f"  (WARNING: {missing} are in neither place)" if missing else ""))
    if not cache.is_dir():
        print("  (no data/features/power_cache here: the cells already in the output folder were kept)")

    lina = Path("data/lina")
    (out / "lina").mkdir(exist_ok=True)
    if (lina / "derived.parquet").exists():
        shutil.copy2(lina / "derived.parquet", out / "lina" / "derived.parquet")
        print("  lina/derived.parquet")
    else:
        print("  no data/lina/derived.parquet: skipped (the folder keeps what it has)")
    if args.no_ndvi:
        print("  --no-ndvi: NDVI left out")
    elif (lina / "ndvi_monthly.csv").exists():
        nd = pd.read_csv(lina / "ndvi_monthly.csv", dtype=NDVI_DTYPES)
        nd["field_id"] = nd["field_id"].cat.rename_categories(lambda c: str(c))
        nd = nd.sort_values(["field_id", "year", "month"])
        nd.to_parquet(out / "lina" / "ndvi_monthly.parquet", index=False, compression="zstd", compression_level=19)
        print(f"  lina/ndvi_monthly.parquet: {len(nd):,} rows, {size(out / 'lina' / 'ndvi_monthly.parquet')}")
    else:
        print("  no data/lina/ndvi_monthly.csv: skipped")
    print(f"deploy data: {size(out)} in {out}")


if __name__ == "__main__":
    main()
