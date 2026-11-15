"""Lina's final files: raw HLS NDVI with clr_frac, wide SMAP with the nearest-field fill, the bare-soil level, the non-cropland note."""
import numpy as np
import pandas as pd
import pytest

from ml_service import precomputed
from ml_service.cdl import noncrop_note
from ml_service.real import bare_from_ndvi
from tests.test_ingest_lina import IDS, analyze, ingest, run, world  # noqa: F401  (world is a fixture)

MONTHS = [f"{y}-{m:02d}" for y in range(2015, 2026) for m in range(1, 13)][3:]          # her SMAP starts in 2015-04


def raw_ndvi(incoming, ids=IDS):
    rows = []
    for f in ids:
        for y in (2023, 2024):
            for m in range(1, 13):
                clr = 0.0 if m == 1 else (0.5 if m == 2 else 1.0)                  # January: no image, February: cloudy
                rows.append((f, f"{y}-{m:02d}", y, m, np.nan if clr == 0 else 0.4, clr, np.nan if clr == 0 else 1.4663))
    pd.DataFrame(rows, columns=["field_id", "date", "year", "month", "ndvi_hls", "clr_frac", "n_obs"]).to_csv(incoming / "hls_ndvi_monthly_raw.csv", index=False)


def wide_smap(incoming, ids):
    rng = np.random.default_rng(1)
    d = pd.DataFrame({"field_id": ids})
    for m in MONTHS:
        d[m] = np.round(0.3 + rng.normal(0, 0.02, len(ids)), 3)
    d.to_csv(incoming / "smap_monthly_wide.csv", index=False)


def place(world, positions):
    """give the county fields their own coordinates (the fixture puts all of them on one point)"""
    p = world["pre"] / "19153.parquet"
    df = pd.read_parquet(p)
    for fid, (lat, lon) in positions.items():
        df.loc[df["field_id"] == fid, ["lat", "lon"]] = lat, lon
    df.to_parquet(p, index=False)
    precomputed.clear_cache()


def test_raw_ndvi_keeps_only_clear_months(world):
    world["incoming"].mkdir()
    raw_ndvi(world["incoming"])
    assert run(world) == 0
    d = pd.read_csv(world["lina"] / "ndvi_monthly.csv")
    assert list(d.columns) == ["field_id", "year", "month", "ndvi_mean", "n_obs"]
    assert not d["month"].isin([1, 2]).any() and len(d) == len(IDS) * 2 * 10          # January (no image) and February (clr_frac 0.5) are gone
    assert (d["n_obs"] == 1).all() and (d["ndvi_mean"] == 0.4).all()                  # the mean count 1.4663 is rounded to 1


def test_wide_smap_is_filled_from_the_nearest_field(world):
    world["incoming"].mkdir()
    place(world, {"P1": (41.00, -93.00), "P2": (41.05, -93.00), "P3": (41.60, -93.00)})      # P2 is ~5.5 km from P1, P3 ~66 km
    wide_smap(world["incoming"], ["P1"])
    assert run(world) == 0
    smap = pd.read_csv(world["lina"] / "smap_monthly.csv", dtype={"field_id": str})
    src = smap.groupby("field_id")["smap_source"].first().to_dict()
    assert src == {"P1": "own", "P2": "nearest_field"}                                # P3 is farther than 10 km: no values, no invention
    a = smap[smap.field_id == "P1"].set_index(["year", "month"])["smap_rootzone"]
    b = smap[smap.field_id == "P2"].set_index(["year", "month"])["smap_rootzone"]
    assert a.equals(b)
    county = pd.read_parquet(world["pre"] / "19153.parquet").set_index("field_id")
    assert county.loc["P1", "smap_source"] == "own" and county.loc["P2", "smap_source"] == "nearest_field"
    assert pd.isna(county.loc["P3", "smap_deficit_share"])


def test_service_warns_about_a_borrowed_smap_and_stays_ok(world):
    world["incoming"].mkdir()
    place(world, {"P1": (41.00, -93.00), "P2": (41.05, -93.00), "P3": (41.06, -93.00)})
    raw_ndvi(world["incoming"])
    wide_smap(world["incoming"], ["P1"])
    assert run(world) == 0
    own, borrowed = analyze("P1"), analyze("P2")
    assert own["status"] == "ok" and borrowed["status"] == "ok"                       # NDVI + SMAP are there, TWI is not needed
    assert not any("nearest field" in w for w in own["warnings"])
    assert any("nearest field" in w for w in borrowed["warnings"])


def test_far_field_has_no_smap_and_is_partial(world):
    world["incoming"].mkdir()
    place(world, {"P1": (41.00, -93.00), "P2": (41.05, -93.00), "P3": (41.06, -93.00)})
    raw_ndvi(world["incoming"])
    assert run(world) == 0
    out = analyze("P1")
    assert out["status"] == "partial" and any("SMAP" in w for w in out["warnings"])


# ---------------------------------------------------------------- bare soil level

def ndvi_frame(field, values):
    """values: {(year, month): ndvi}"""
    rows = [(field, y, m, v, 3.0) for (y, m), v in values.items()]
    return pd.DataFrame(rows, columns=["field_id", "year", "month", "ndvi_mean", "n_obs"]).astype({"year": "int16", "month": "int8"})


def test_stubble_is_bare_at_the_new_level():
    nd = ndvi_frame("f", {(2024, 1): 0.26, (2024, 7): 0.80})
    bare = bare_from_ndvi(nd, "f", {2024: "corn"})
    assert bare[1] == 1.0 and bare[7] == 0.0                                          # 0.26 is residue: under 0.30 (it was missed at 0.2)


def test_green_winter_wheat_is_not_called_bare():
    nd = ndvi_frame("f", {(2024, 2): 0.27, (2023, 12): 0.27})                         # dormant wheat, NDVI 0.27 in winter
    assert bare_from_ndvi(nd, "f", {2024: "corn"})[2] == 1.0
    wheat = bare_from_ndvi(nd, "f", {2024: "winter_wheat"})
    assert wheat[2] == 0.0 and wheat[12] == 0.0                                       # Feb 2024 is the 2024 crop; Dec 2023 belongs to it too


# ---------------------------------------------------------------- not cropland

def test_noncrop_history_gets_a_note():
    assert noncrop_note({2021: 1, 2022: 5, 2023: 176, 2024: 5, 2025: 123}) is not None
    assert noncrop_note({2021: 1, 2022: 5, 2023: 176, 2024: 5, 2025: 1}) is None       # one year of grass is a rotation, not a lawn
