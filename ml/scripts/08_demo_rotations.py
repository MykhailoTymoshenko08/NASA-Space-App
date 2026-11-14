"""
step 8 - show the rotation plan (ml_service/rotations.py) for real fields.

usage:
  python scripts/08_demo_rotations.py                              # the same 5 fields as the ranking demo
  python scripts/08_demo_rotations.py --fields 191825002125636 --temp 3 --precip -30
  python scripts/08_demo_rotations.py --priorities erosion=1 income=0.2 --irrigated
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ml_service.field_context import load_field_context  # noqa: E402
from ml_service.ranking import load_assets  # noqa: E402
from ml_service.rotations import plan_rotations  # noqa: E402
from ml_service.stress import compute_stress, load_ndvi_monthly  # noqa: E402

DEFAULT_FIELDS = ["191825002125636", "171825009992830", "311825007895558", "201825006971812", "201825004606778"]
NAMES = {"water": "вода", "soil_health": "ґрунт", "nitrogen": "азот", "erosion": "ерозія", "income": "дохід", "overall": "ПІДСУМОК"}


def show(r: dict, ctx) -> None:
    cr = r["current_rotation"]
    print("\n" + "=" * 118)
    print(f"ПОЛЕ {ctx.field_id} | {ctx.state} | історія CSB: " + " ".join(f"{y % 100}:{'/'.join(p[:4] for p in c.split('+'))}" for y, c in sorted((ctx.history_rich or ctx.history).items())))
    print(f"  поточна сівозміна: {cr['label']}   (цикл {cr['cycle_years']} р., збіг {cr['agreement']:.0%}, вікно {cr['window_years']} р., довіра {cr['confidence']})")
    if r["scenario"]["temp_delta_c"] or r["scenario"]["precip_change_pct"]:
        print(f"  СЦЕНАРІЙ: {r['scenario']['temp_delta_c']:+.1f}°C, опади {r['scenario']['precip_change_pct']:+.0f}%")
    st = r["stress"]
    if st and st["active"]:
        print(f"  ⚠ СТРЕС МИНУЛОГО СЕЗОНУ: NDVI на {st['pct_below']:.0f}% нижче за сусідів (z = {st['z']})")
    print(f"\n  {'':<9}{'сівозміна':<58}{'ПІДСУМОК':>9}{'Δ':>5}  {'вода':>5}{'ґрунт':>6}{'азот':>6}{'ерозія':>7}{'дохід':>6}   голих дн  ерозія т/га  вода мм  N кг/га")
    for s in r["strategies"]:
        sc, m, d = s["scores"], s["metrics"], r["details"][s["id"]]
        delta = "" if s["delta_vs_current"] is None else f"{s['delta_vs_current']['overall']:+d}"
        print(f"  {s['id']:<9}{s['name']:<58}{sc['overall']:>9}{delta:>5}  {sc['water']:>5}{sc['soil_health']:>6}{sc['nitrogen']:>6}{sc['erosion']:>7}{sc['income']:>6}"
              f"   {m['bare_days_yr']:>7}  {m['erosion_t_ha_yr']:>10}  {m['water_use_mm_yr']:>7}  {d['n_balance_kg_ha_yr']:>+6.0f}")
    for s in r["strategies"][1:]:
        d = r["details"][s["id"]]
        print(f"\n  {s['id']} [{d['logic']}] {s['name']}   (довіра {s['confidence']}, відповідність полю {d['fit']:.0f}/100, цикл шкідників розірвано: {'так' if d['pest_cycle_break'] else 'НІ'})")
        print(f"      {s['why']}")
        for b in s["benefits"][:3]:
            print(f"      ＋ {b}")
        for x in s["risks"][:3]:
            print(f"      － {x}")
        print(f"      ? з агрономом: {'; '.join(s['check_with_agronomist'])}")
    print("\n  прогалини в даних: " + " | ".join(r["strategies"][0]["data_gaps"]))


def main() -> None:
    p = argparse.ArgumentParser(description="rotation plan demo")
    p.add_argument("--fields", nargs="*", default=DEFAULT_FIELDS)
    p.add_argument("--temp", type=float, default=0.0, help="temp_delta_c, -2..4")
    p.add_argument("--precip", type=float, default=0.0, help="precip_change_pct, -40..20")
    p.add_argument("--priorities", nargs="*", default=[], help="e.g. erosion=1 income=0.2 (default 0.5 each)")
    p.add_argument("--irrigated", action="store_true")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--lang", default="uk", choices=["uk", "en"])
    args = p.parse_args()

    a = load_assets()
    prio = {k: float(v) for k, v in (x.split("=") for x in args.priorities)}
    ndvi = load_ndvi_monthly("data/lina")
    for fid in args.fields:
        ctx = load_field_context(fid, a, scenario=(args.temp, args.precip))
        stress = None
        if ndvi is not None:   # the stress rule switches on by itself when Lina's NDVI file exists
            import pandas as pd
            hist = pd.read_parquet("data/fields/crop_history.parquet")
            slug = {c["cdl_code"]: s for s, c in a.candidates.items()}
            crop_of = hist.assign(crop=hist["cdl_code"].map(slug).fillna("other"))[["field_id", "year", "crop"]]
            state_of = pd.read_parquet("data/fields/fields.parquet", columns=["field_id", "state_fips"]).set_index("field_id")["state_fips"]
            from ml_service.rotations import load_settings
            stress = compute_stress(ndvi, crop_of, state_of, fid, ctx.target_year - 1, ctx.prev_crops[0], load_settings()["stress"])
        show(plan_rotations(ctx, a, priorities=prio or None, farmer_input={"irrigated": True} if args.irrigated else None,
                            lang=args.lang, n_strategies=args.n, stress=stress), ctx)


if __name__ == "__main__":
    main()
