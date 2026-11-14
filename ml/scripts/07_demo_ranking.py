"""
step 7 - show the crop ranking (ml_service/ranking.py) for real fields.

usage:
  python scripts/07_demo_ranking.py                       # 5 fields: IA, IL, NE, KS (after fallow), KS (after sorghum)
  python scripts/07_demo_ranking.py --fields 191825... --irrigated
  python scripts/07_demo_ranking.py --lang en
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ml_service.feature_text import crop_name  # noqa: E402
from ml_service.field_context import load_field_context  # noqa: E402
from ml_service.ranking import FIPS, load_assets, rank_crops  # noqa: E402

# (state, what grew last year): one field of each kind
DEFAULT_PICKS = [("IA", "soybean"), ("IL", "corn"), ("NE", "winter_wheat"), ("KS", "other"), ("KS", "sorghum")]


def pick_fields(a, target_year: int) -> list[str]:
    fields = pd.read_parquet("data/fields/fields.parquet", columns=["field_id", "state_fips"]).sample(frac=1, random_state=11)
    hist = pd.read_parquet("data/fields/crop_history.parquet")
    last = hist[hist["year"] == target_year - 1].set_index("field_id")["cdl_code"]
    cdl_to_slug = {c["cdl_code"]: s for s, c in a.candidates.items()}
    kind = last.map(lambda c: cdl_to_slug.get(int(c), "other"))
    out = []
    for state, prev in DEFAULT_PICKS:
        ids = fields[(fields["state_fips"] == FIPS[state]) & fields["field_id"].map(kind).eq(prev)]["field_id"]
        ids = [i for i in ids if i not in out]
        out.append(ids[0])
    return out


def show(r: dict, ctx, lang: str) -> None:
    uk = lang == "uk"
    print("\n" + "=" * 110)
    print(f"ПОЛЕ {ctx.field_id}  |  {ctx.state}  ({ctx.lat:.2f}, {ctx.lon:.2f})  |  {'зрошується' if r['irrigated'] else 'без зрошення'}")
    print(f"  що росло: торік {crop_name(ctx.prev_crops[0], lang)}, позаторік {crop_name(ctx.prev_crops[1], lang)}")
    s = ctx.soil
    print(f"  ґрунт: pH {s['ph_h2o']:.1f}, глина {s['clay_pct']:.0f}%, органічний C {s['soc_pct']:.1f}%, засоленість {s['ec_ds_m'] if s['ec_ds_m'] is None else round(s['ec_ds_m'], 2)} дСм/м | "
          f"ухил {ctx.slope_pct:.1f}%")
    n = ctx.climate_norm
    print(f"  клімат (норма): тепло {n['gdd_grow']:.0f} °C·днів, опади {n['precip_grow']:.0f} мм, зимовий мінімум {ctx.winter_tmin_c:.1f}°C")

    print(f"\n  {'культура':<20}{'стан':<10}{'бал 0-100':>10}{'ймов.моделі':>13}{'×перехід':>10}{'×придатн.':>11}{'×правила':>10}")
    for c in r["crops"]:
        p = c["parts"]
        src = "" if p["model_prob_source"] == "model" else "*"
        print(f"  {c['name']:<20}{('заблок.' if c['status'] == 'blocked' else 'ок'):<10}{c['relative']:>10.1f}"
              f"{p['model_prob']:>12.3f}{src or ' '}{p['transition']:>9.2f}{p['suitability']:>11.2f}{p['rules']:>10.2f}")
    print("  (* = ймовірність не з моделі: нейтральне значення для культури, яку веде лише правила)")

    print("\n  ТОП-3:")
    for c in r["top3"]:
        weak = "  ⚠ слабка альтернатива" if c["weak"] else ""
        print(f"   #{c['rank']} {c['name']}  [{c['role']}]  бал {c['relative']:.1f}/100{weak}")
        for f in c["main_factors"]:
            print(f"        {'▲' if f['direction'] == '+' else '▼'} {f['text']}")
        shown = {f["text"] for f in c["main_factors"]}
        extra = [ad["text"] for ad in c["adjustments"] if ad["multiplier"] != 1.0 and ad["text"] not in shown]
        for ad in extra[:3]:
            print(f"        ✎ {ad}")
    blocked = [c for c in r["crops"] if c["status"] == "blocked"]
    if blocked:
        print("\n  ВИКЛЮЧЕНО:")
        for c in blocked:
            for reason in c["blocked_reasons"]:
                print(f"   ✗ {c['name']}: {reason}")
    for g in r["data_gaps"]:
        print(f"  ⓘ {g}")


def main() -> None:
    p = argparse.ArgumentParser(description="crop ranking demo")
    p.add_argument("--fields", nargs="*", help="field ids (default: 5 picked fields)")
    p.add_argument("--irrigated", action="store_true")
    p.add_argument("--lang", default="uk", choices=["uk", "en"])
    p.add_argument("--target-year", type=int, default=2026)
    args = p.parse_args()

    a = load_assets()
    for fid in args.fields or pick_fields(a, args.target_year):
        ctx = load_field_context(fid, a, target_year=args.target_year)
        show(rank_crops(ctx, a, lang=args.lang, irrigated=True if args.irrigated else None), ctx, args.lang)


if __name__ == "__main__":
    main()
