"""
step 10 - take Lina's CSV files, check them, install them in data/lina/ and rebuild what depends on them.

files (any of them can be missing). the canonical formats below are what the service reads; Lina's real GEE outputs (ml/gee/*.py)
are accepted under their own names and converted on the way in:
  ndvi_monthly.csv  field_id, year, month, ndvi_mean, n_obs      NDVI -1..1; n_obs >= 0 (ndvi_mean may be empty only when n_obs = 0)
     <- hls_ndvi_monthly_long.csv  field_id, date, year, month, ndvi_hls, n_obs     (ndvi_hls -> ndvi_mean, date dropped)
  ndvi_season.csv   field_id, year, ndvi_peak, ndvi_peak_doy     NDVI -1..1; doy 1..366   (kept for the NDVI model, not used by the service yet)
  smap_monthly.csv  field_id, year, month, smap_rootzone         0..0.6 m3/m3
     <- smap_monthly_long.csv      field_id, date, year, month, smap_rootzone          (date dropped)
  terrain.csv       field_id, slope_pct [, twi, slope_class, slope_pct_p90]   slope 0..100 %; twi finite (-10..40) and optional
     <- terrain2.csv               field_id, slope_deg, slope_deg_p90    slope_pct = tan(radians(slope_deg)) * 100 (the field median);
                                   slope_pct_p90 is the same for the 90th percentile and is informational only. no twi in her file:
                                   the high-TWI rule stays off (ctx.twi is empty) until a TWI arrives
  years from 2015 on are all kept (ranges allow 2015..2026)

checks: required columns, number formats, ranges, empty values, duplicate keys, field_ids that we do not know (neither in the 2000-field
sample nor in a precomputed county). bad rows are dropped and counted; when more than --max-bad-share of a file is bad the
file is REFUSED and nothing is written.

what happens next (this is what makes the service pick the files up automatically):
  data/lina/<file>.csv        the cleaned file (the old one goes to data/lina/_previous/). ndvi_monthly.csv is read at request
                              time: real bare-soil months in the timeline and the last-season stress rule
  data/lina/derived.parquet   per field: slope_pct, twi, slope_class (terrain) and smap_julaug_mean, smap_deficit_share (smap)
                              smap_deficit_share = share of years whose Jul-Aug root-zone moisture was under the dry level of the state
                              (25th percentile of all fields and years of that state; needs >= 3 years)
  data/precomputed/*.parquet  rebuilt: columns slope_pct, twi, slope_class, smap_julaug_mean, smap_deficit_share filled in
                              (so the Docker image, which has no data/lina, still has them)

usage:
  python scripts/10_ingest_lina.py --incoming ~/Downloads/lina
  python scripts/10_ingest_lina.py --incoming ~/Downloads/lina --dry-run        # only the report
  python scripts/10_ingest_lina.py --incoming ~/Downloads/lina_demo --merge     # second field set: add to the installed files, not replace
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

DRY_LEVEL_QUANTILE = 0.25
MIN_SMAP_YEARS = 3
FIPS_STATE = {"19": "IA", "17": "IL", "20": "KS", "31": "NE"}

# file -> (required columns, optional columns, numeric rules {column: (low, high, kind)})
SPECS = {
    "ndvi_monthly.csv": dict(key=["field_id", "year", "month"], required=["field_id", "year", "month", "ndvi_mean", "n_obs"], optional=[],
                             ranges={"year": (2015, 2026, "int"), "month": (1, 12, "int"), "ndvi_mean": (-1.0, 1.0, "float"), "n_obs": (0, 1e6, "int")}),
    "ndvi_season.csv": dict(key=["field_id", "year"], required=["field_id", "year", "ndvi_peak", "ndvi_peak_doy"], optional=[],
                            ranges={"year": (2015, 2026, "int"), "ndvi_peak": (-1.0, 1.0, "float"), "ndvi_peak_doy": (1, 366, "int")}),
    "smap_monthly.csv": dict(key=["field_id", "year", "month"], required=["field_id", "year", "month", "smap_rootzone"], optional=[],
                             ranges={"year": (2015, 2026, "int"), "month": (1, 12, "int"), "smap_rootzone": (0.0, 0.6, "float")}),
    "terrain.csv": dict(key=["field_id"], required=["field_id", "slope_pct"], optional=["twi", "slope_class", "slope_pct_p90"],
                        ranges={"slope_pct": (0.0, 100.0, "float"), "slope_pct_p90": (0.0, 100.0, "float"), "twi": (-10.0, 40.0, "float")}),
}

# canonical name -> the names Lina's scripts write (the canonical name wins when both are in the folder)
ALIASES = {"ndvi_monthly.csv": "hls_ndvi_monthly_long.csv", "smap_monthly.csv": "smap_monthly_long.csv", "terrain.csv": "terrain2.csv"}


def adapt(name: str, raw: pd.DataFrame) -> pd.DataFrame:
    """Lina's column names and units -> ours (a file already in our format passes through unchanged)"""
    df = raw.copy()
    if name == "ndvi_monthly.csv" and "ndvi_hls" in df.columns and "ndvi_mean" not in df.columns:
        df = df.rename(columns={"ndvi_hls": "ndvi_mean"})
    if name == "terrain.csv" and "slope_deg" in df.columns and "slope_pct" not in df.columns:
        # percent = tan(angle) * 100. 90 degrees or a negative angle gives a value outside 0..100 and is dropped by the range check
        for deg, pct in (("slope_deg", "slope_pct"), ("slope_deg_p90", "slope_pct_p90")):
            if deg in df.columns:
                df[pct] = (np.tan(np.radians(pd.to_numeric(df[deg], errors="coerce"))) * 100).round(2)
    return df


class Refused(Exception):
    pass


def known_fields(fields_dir: Path, precomputed_dir: Path) -> pd.Series:
    """field_id -> state, for the 2000-field sample and every precomputed county"""
    parts = []
    f = fields_dir / "fields.parquet"
    if f.exists():
        d = pd.read_parquet(f, columns=["field_id", "state_fips"])
        parts.append(d.assign(state=d["state_fips"].map(FIPS_STATE)).set_index("field_id")["state"])
    for p in sorted(precomputed_dir.glob("*.parquet")):
        d = pd.read_parquet(p, columns=["field_id", "state"])
        parts.append(d.assign(field_id=d["field_id"].astype(str)).set_index("field_id")["state"])
    return pd.concat(parts) if parts else pd.Series(dtype=object)


def validate(name: str, raw: pd.DataFrame, known: pd.Series, max_bad_share: float) -> tuple[pd.DataFrame, dict]:
    """returns the cleaned frame and a report. raises Refused when the file cannot be used."""
    spec = SPECS[name]
    missing = [c for c in spec["required"] if c not in raw.columns]
    if missing:
        raise Refused(f"missing columns: {missing} (found {list(raw.columns)})")
    df = raw[[c for c in spec["required"] + spec["optional"] if c in raw.columns]].copy()
    n0 = len(df)
    if n0 == 0:
        raise Refused("the file has no rows")
    bad = pd.Series(False, index=df.index)
    reasons: dict[str, int] = {}

    def mark(mask: pd.Series, why: str) -> None:
        nonlocal bad
        new = mask & ~bad
        if new.any():
            reasons[why] = reasons.get(why, 0) + int(new.sum())
        bad = bad | mask

    df["field_id"] = df["field_id"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)   # ids written as 191825000314326.0
    mark(df["field_id"].isin(["", "nan", "None"]), "empty field_id")
    mark(~df["field_id"].isin(known.index), "unknown field_id")

    for col, (lo, hi, kind) in spec["ranges"].items():
        if col not in df.columns:                                   # an optional column the file does not have
            continue
        num = pd.to_numeric(df[col], errors="coerce")
        empty = num.isna()
        if name == "ndvi_monthly.csv" and col == "ndvi_mean":      # a month without a cloud-free image has no NDVI and n_obs = 0
            n_obs = pd.to_numeric(df["n_obs"], errors="coerce")
            mark(empty & (n_obs.fillna(0) > 0), f"{col}: empty although n_obs > 0")
        elif name == "terrain.csv" and col == "twi":               # TWI can be absent for a field; slope cannot
            pass
        else:
            mark(empty, f"{col}: empty or not a number")
        out = ~empty & ((num < lo) | (num > hi) | np.isinf(num))
        mark(out, f"{col}: outside {lo}..{hi}")
        if kind == "int":
            mark(~empty & (num != num.round()), f"{col}: not a whole number")
        df[col] = num
    dup = df.duplicated(spec["key"], keep="last") & ~bad
    reasons["duplicate key (last kept)"] = int(dup.sum()) if dup.any() else 0
    clean = df[~bad & ~df.duplicated(spec["key"], keep="last")].copy()
    for col in ("year", "month", "n_obs", "ndvi_peak_doy"):
        if col in clean:
            clean[col] = clean[col].astype(int)
    reasons = {k: v for k, v in reasons.items() if v}
    n_bad = int(bad.sum())
    report = {"rows": n0, "kept": len(clean), "dropped": n0 - len(clean), "bad": n_bad, "bad_share": n_bad / n0, "reasons": reasons,
              "fields": int(clean["field_id"].nunique()), "years": sorted(clean["year"].unique().tolist()) if "year" in clean else []}
    if report["bad_share"] > max_bad_share:
        raise Refused(f"{n_bad:,} of {n0:,} rows ({report['bad_share']:.1%}) are bad, more than the allowed {max_bad_share:.0%}: {reasons}")
    if clean.empty:
        raise Refused("no usable rows left after the checks")
    return clean, report


def derive(terrain: pd.DataFrame | None, smap: pd.DataFrame | None, known: pd.Series) -> pd.DataFrame:
    """one row per field: NASADEM terrain and the SMAP dry-year share"""
    parts = []
    if terrain is not None:
        cols = [c for c in ("field_id", "slope_pct", "twi", "slope_class") if c in terrain.columns]
        parts.append(terrain[cols].set_index("field_id"))
    if smap is not None:
        ja = smap[smap["month"].isin([7, 8])].groupby(["field_id", "year"], as_index=False)["smap_rootzone"].mean()
        ja["state"] = ja["field_id"].map(known)
        ja["dry_level"] = ja.groupby("state")["smap_rootzone"].transform(lambda s: s.quantile(DRY_LEVEL_QUANTILE))
        ja["dry"] = ja["smap_rootzone"] < ja["dry_level"]
        g = ja.groupby("field_id")
        s = pd.DataFrame({"smap_julaug_mean": g["smap_rootzone"].mean(), "smap_deficit_share": g["dry"].mean(), "smap_years": g.size()})
        s.loc[s["smap_years"] < MIN_SMAP_YEARS, "smap_deficit_share"] = np.nan        # too few years to call a field chronically dry
        parts.append(s.drop(columns="smap_years"))
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, axis=1).reset_index().rename(columns={"index": "field_id"})


def rebuild_precomputed(precomputed_dir: Path, derived: pd.DataFrame) -> dict[str, int]:
    """put the derived columns into every county file; returns {county file: fields that got terrain / smap}"""
    out = {}
    d = derived.set_index("field_id")
    for p in sorted(precomputed_dir.glob("*.parquet")):
        df = pd.read_parquet(p)
        ids = df["field_id"].astype(str)
        for col in ("slope_pct", "twi", "slope_class", "smap_julaug_mean", "smap_deficit_share"):
            if col in d.columns:
                df[col] = ids.map(d[col]).to_numpy()
            elif col not in df.columns:
                df[col] = np.nan if col != "slope_class" else None
        tmp = p.with_suffix(".tmp")
        df.to_parquet(tmp, index=False)
        tmp.replace(p)
        out[p.name] = int(ids.isin(d.index).sum())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="validate and install Lina's files")
    ap.add_argument("--incoming", required=True, help="folder with her CSV files")
    ap.add_argument("--lina", default="data/lina")
    ap.add_argument("--fields", default="data/fields")
    ap.add_argument("--precomputed", default="data/precomputed")
    ap.add_argument("--max-bad-share", type=float, default=0.05)
    ap.add_argument("--merge", action="store_true",
                    help="add the rows to the installed files instead of replacing them (second field set; same key = the new row wins)")
    ap.add_argument("--dry-run", action="store_true", help="check and report only, write nothing")
    args = ap.parse_args()

    incoming, lina, pre = Path(args.incoming), Path(args.lina), Path(args.precomputed)
    known = known_fields(Path(args.fields), pre)
    print(f"known fields: {len(known):,} (sample + precomputed counties)")
    cleaned: dict[str, pd.DataFrame] = {}
    refused = []
    for name in SPECS:
        src = incoming / name
        if not src.exists() and (incoming / ALIASES.get(name, name)).exists():
            src = incoming / ALIASES[name]
        if not src.exists():
            print(f"\n{name}: not in the incoming folder, skipped")
            continue
        print(f"\n{name}" + (f"  (from {src.name})" if src.name != name else ""))
        try:
            clean, rep = validate(name, adapt(name, pd.read_csv(src, dtype={"field_id": str})), known, args.max_bad_share)
        except Refused as e:
            print(f"  REFUSED: {e}")
            refused.append(name)
            continue
        cleaned[name] = clean
        print(f"  rows {rep['rows']:,} -> kept {rep['kept']:,} | fields {rep['fields']:,} | years {rep['years']}")
        for why, n in rep["reasons"].items():
            print(f"    dropped {n:,}: {why}")
        cov = known.index.isin(clean["field_id"])
        print(f"  covers {cov.sum():,} of {len(known):,} known fields ({cov.mean():.0%})")

    if args.dry_run or not cleaned:
        print("\ndry run: nothing written" if args.dry_run else "\nnothing to install")
        return 1 if refused else 0

    lina.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for name, df in cleaned.items():
        dst = lina / name
        if dst.exists():
            (lina / "_previous").mkdir(exist_ok=True)
            shutil.copy2(dst, lina / "_previous" / f"{stamp}-{name}")
        if args.merge and dst.exists():
            df = pd.concat([pd.read_csv(dst, dtype={"field_id": str}), df], ignore_index=True).drop_duplicates(SPECS[name]["key"], keep="last")
        df.to_csv(dst, index=False)
        print(f"installed {dst} ({len(df):,} rows)")

    # derived features come from the files now installed (an earlier terrain.csv still counts when only smap is new)
    def installed(name):
        return pd.read_csv(lina / name, dtype={"field_id": str}) if (lina / name).exists() else None
    derived = derive(installed("terrain.csv"), installed("smap_monthly.csv"), known)
    if len(derived):
        derived.to_parquet(lina / "derived.parquet", index=False)
        print(f"wrote {lina / 'derived.parquet'}: {len(derived):,} fields")
        for fname, n in rebuild_precomputed(pre, derived).items():
            print(f"rebuilt {fname}: {n:,} fields got terrain / smap values")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
