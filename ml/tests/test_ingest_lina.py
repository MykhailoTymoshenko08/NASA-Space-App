"""scripts/10_ingest_lina.py on synthetic files in Lina's format, and the service picking them up (no network)."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from ml_service import power_client, precomputed, season_climate, soil_sda
from ml_service.main import app
from tests.test_analyze_real import FAKE_SOIL, LAT, LON, synthetic_power

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ingest10", ROOT / "scripts" / "10_ingest_lina.py")
ingest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingest)

SAMPLE = ["S1", "S2", "S3"]                # fields of the "2000-field sample"
COUNTY = ["P1", "P2", "P3"]                # fields of a precomputed county
IDS = SAMPLE + COUNTY
YEARS = range(2018, 2026)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """a tiny world: a sample table, one precomputed county with a synthetic POWER cell, and an empty data/lina"""
    fields, pre, lina, power = tmp_path / "fields", tmp_path / "pre", tmp_path / "lina", tmp_path / "power"
    for d in (fields, pre, lina, power):
        d.mkdir()
    pd.DataFrame({"field_id": SAMPLE, "state_fips": "19"}).to_parquet(fields / "fields.parquet", index=False)
    monkeypatch.setenv("ML_POWER_CACHE_DIR", str(power))
    synthetic_power(power_client.cell_path(LAT, LON))
    snap = power_client.snap_to_cell(LAT, LON)
    clim = season_climate.field_climate(season_climate.load_daily(str(power_client.cell_path(LAT, LON)), snap[0]), 2025)
    rows = []
    for fid in COUNTY:
        meta = {"field_id": fid, "state": "IA", "county_fips5": "19153", "lat": LAT, "lon": LON, "area_ha": 40.0, "csb_acres": 99.0}
        rows.append(precomputed.build_row(meta, {y: (1 if y % 2 == 0 else 5) for y in YEARS}, dict(FAKE_SOIL), clim, power_client.cell_key(*snap)))
    pd.DataFrame(rows).to_parquet(pre / "19153.parquet", index=False)
    monkeypatch.setenv("ML_PRECOMPUTED_DIR", str(pre))
    monkeypatch.setenv("ML_LINA_DIR", str(lina))
    monkeypatch.setenv("ML_MODE", "real")
    precomputed.clear_cache()
    return dict(fields=fields, pre=pre, lina=lina, incoming=tmp_path / "incoming", tmp=tmp_path)


def lina_files(incoming: Path, ids=IDS, **bad):
    """files in her format: monthly NDVI Apr-Oct, SMAP Jun-Aug, terrain. `bad` injects problems"""
    incoming.mkdir(exist_ok=True)
    rng = np.random.default_rng(3)
    ndvi = [(f, y, m, float(np.clip(0.15 + 0.65 * np.exp(-((m - 7.5) ** 2) / 4) + rng.normal(0, 0.02), -1, 1)), 3)
            for f in ids for y in YEARS for m in range(4, 11)]
    smap = [(f, y, m, float(0.3 + rng.normal(0, 0.02) - (0.15 if f == "P1" and y % 2 == 0 else 0))) for f in ids for y in YEARS for m in (6, 7, 8)]
    terrain = [(f, 2.0 + i, 8.0 + 3 * i, ["flat", "gentle", "moderate"][i % 3]) for i, f in enumerate(ids)]
    d = {"ndvi_monthly.csv": pd.DataFrame(ndvi, columns=["field_id", "year", "month", "ndvi_mean", "n_obs"]),
         "smap_monthly.csv": pd.DataFrame(smap, columns=["field_id", "year", "month", "smap_rootzone"]),
         "terrain.csv": pd.DataFrame(terrain, columns=["field_id", "slope_pct", "twi", "slope_class"])}
    for fn, mod in bad.items():
        mod(d[fn])
    for fn, df in d.items():
        df.to_csv(incoming / fn, index=False)
    return d


def run(world, *extra):
    import sys
    sys.argv = ["10_ingest_lina.py", "--incoming", str(world["incoming"]), "--lina", str(world["lina"]), "--fields", str(world["fields"]),
                "--precomputed", str(world["pre"]), *extra]
    return ingest.main()


# ---------------------------------------------------------------- validation

def test_good_files_pass_with_no_drops(world):
    d = lina_files(world["incoming"])
    known = ingest.known_fields(world["fields"], world["pre"])
    assert set(known.index) == set(IDS) and known["P1"] == "IA"
    for name in d:
        clean, rep = ingest.validate(name, pd.read_csv(world["incoming"] / name, dtype={"field_id": str}), known, 0.05)
        assert rep["dropped"] == 0 and rep["fields"] == len(IDS) and len(clean) == len(d[name])


def test_bad_rows_are_dropped_and_counted(world):
    def bad_ndvi(df):
        df.loc[0, "ndvi_mean"] = 1.7                      # outside -1..1
        df.loc[1, "ndvi_mean"] = np.nan                   # empty although n_obs > 0
        df.loc[2, "field_id"] = "NOPE"                    # unknown field
        df.loc[3, "month"] = 13                           # impossible month
        df.loc[4, ["ndvi_mean", "n_obs"]] = [np.nan, 0]   # a month without an image: allowed
        df.loc[len(df)] = df.loc[10]                      # a duplicate key
    def bad_smap(df):
        df.loc[0, "smap_rootzone"] = 0.9
    def bad_terrain(df):
        df.loc[0, "slope_pct"] = 140.0
    lina_files(world["incoming"], **{"ndvi_monthly.csv": bad_ndvi, "smap_monthly.csv": bad_smap, "terrain.csv": bad_terrain})
    known = ingest.known_fields(world["fields"], world["pre"])
    read = lambda n: pd.read_csv(world["incoming"] / n, dtype={"field_id": str})
    clean, rep = ingest.validate("ndvi_monthly.csv", read("ndvi_monthly.csv"), known, 0.05)
    assert rep["bad"] == 4 and rep["dropped"] == 5                                        # 4 bad rows + 1 duplicate
    assert set(rep["reasons"]) == {"ndvi_mean: outside -1.0..1.0", "ndvi_mean: empty although n_obs > 0", "unknown field_id",
                                   "month: outside 1..12", "duplicate key (last kept)"}
    assert clean["ndvi_mean"].isna().sum() == 1 and clean["ndvi_mean"].dropna().between(-1, 1).all()   # the no-image month stays, empty
    assert ingest.validate("smap_monthly.csv", read("smap_monthly.csv"), known, 0.05)[1]["reasons"] == {"smap_rootzone: outside 0.0..0.6": 1}
    # 1 bad row of 6 is 17%: refused at the default 5%, accepted when the threshold is raised
    with pytest.raises(ingest.Refused, match="more than the allowed 5%"):
        ingest.validate("terrain.csv", read("terrain.csv"), known, 0.05)
    assert ingest.validate("terrain.csv", read("terrain.csv"), known, 0.2)[1]["reasons"] == {"slope_pct: outside 0.0..100.0": 1}


def test_a_file_that_is_too_broken_is_refused(world):
    lina_files(world["incoming"], **{"smap_monthly.csv": lambda df: df.__setitem__("smap_rootzone", df["smap_rootzone"] * 5)})
    known = ingest.known_fields(world["fields"], world["pre"])
    read = lambda n: pd.read_csv(world["incoming"] / n, dtype={"field_id": str})
    with pytest.raises(ingest.Refused, match="more than the allowed"):
        ingest.validate("smap_monthly.csv", read("smap_monthly.csv"), known, 0.05)
    with pytest.raises(ingest.Refused, match="missing columns"):
        ingest.validate("terrain.csv", read("terrain.csv").drop(columns="slope_pct"), known, 0.05)
    with pytest.raises(ingest.Refused, match="no rows"):
        ingest.validate("terrain.csv", read("terrain.csv").head(0), known, 0.05)


def test_ids_written_as_floats_and_optional_slope_class(world):
    d = lina_files(world["incoming"])
    t = d["terrain.csv"].drop(columns="slope_class")
    t["field_id"] = ["S1.0", "S2.0", "S3.0", "P1.0", "P2.0", "P3.0"]
    known = ingest.known_fields(world["fields"], world["pre"])
    clean, rep = ingest.validate("terrain.csv", t, known, 0.05)
    assert rep["dropped"] == 0 and "slope_class" not in clean.columns and set(clean["field_id"]) == set(IDS)


# ---------------------------------------------------------------- derived values

def test_smap_deficit_share_uses_the_dry_level_of_the_state(world):
    d = lina_files(world["incoming"])
    known = ingest.known_fields(world["fields"], world["pre"])
    der = ingest.derive(d["terrain.csv"], d["smap_monthly.csv"], known).set_index("field_id")
    assert der.loc["P1", "smap_deficit_share"] == pytest.approx(0.5, abs=0.13)         # P1 is dry in every second year
    assert der.loc["P2", "smap_deficit_share"] < 0.4 and der["smap_deficit_share"].max() == der.loc["P1", "smap_deficit_share"]
    assert der.loc["S1", "slope_pct"] == 2.0 and der.loc["P2", "slope_pct"] == 6.0 and der.loc["P2", "slope_class"] == "gentle"
    few = d["smap_monthly.csv"][d["smap_monthly.csv"]["year"].isin([2024, 2025])]       # only 2 years: no verdict
    assert ingest.derive(None, few, known)["smap_deficit_share"].isna().all()


# ---------------------------------------------------------------- the whole run

def test_end_to_end_install_and_rebuild(world):
    lina_files(world["incoming"])
    assert run(world) == 0
    for fn in ("ndvi_monthly.csv", "smap_monthly.csv", "terrain.csv", "derived.parquet"):
        assert (world["lina"] / fn).exists()
    county = pd.read_parquet(world["pre"] / "19153.parquet").set_index("field_id")
    assert county.loc["P2", "slope_pct"] == 6.0 and county.loc["P2", "twi"] == 20.0 and county.loc["P2", "slope_class"] == "gentle"
    assert county.loc["P1", "smap_deficit_share"] >= 0.4 and "slope_r" in county.columns          # SSURGO slope stays
    run(world)                                                                                     # a second delivery
    assert len(list((world["lina"] / "_previous").glob("*terrain.csv"))) == 1                      # the old file was kept


def test_dry_run_and_refusal_write_nothing(world):
    lina_files(world["incoming"])
    assert run(world, "--dry-run") == 0 and not list(world["lina"].iterdir())
    lina_files(world["incoming"], **{"terrain.csv": lambda df: df.__setitem__("slope_pct", 500.0)})
    assert run(world) == 1                                                                         # terrain refused ...
    assert not (world["lina"] / "terrain.csv").exists() and (world["lina"] / "ndvi_monthly.csv").exists()   # ... the others installed


# ---------------------------------------------------------------- the service picks the files up

def analyze(field_id):
    b = {"field": {"field_id": field_id, "centroid": {"lat": LAT, "lon": LON}, "admin": {"state": "IA"}}, "options": {"language": "en"}}
    return TestClient(app).post("/ml/v1/analyze", json=b).json()


def test_service_uses_the_files_for_a_precomputed_field(world, monkeypatch):
    before = analyze("P1")
    assert before["status"] == "partial" and {s["id"] for s in before["sources"]} == {"csb", "power", "ssurgo"}
    text = " ".join(before["warnings"])
    assert "NDVI" in text and "SMAP" in text and "TWI" in text and "NASADEM" in text

    lina_files(world["incoming"], ids=IDS)
    run(world)
    after = analyze("P1")
    assert {"nasadem", "smap", "landsat_ndvi"} <= {s["id"] for s in after["sources"]}
    text = " ".join(after["warnings"])
    assert "NDVI" not in text and "SMAP" not in text and "TWI" not in text and "NASADEM" not in text
    assert after["status"] == "ok"                                                                  # nothing is missing any more
    tl = after["vulnerability_timeline"]
    assert {m["bare_soil_source"] for m in tl[3:10]} == {"landsat_ndvi"} and tl[0]["bare_soil_source"] == "crop_calendar"
    cs = {c["crop"]: c for c in after["crop_suitability"]}
    assert cs["winter_wheat"]["parts"]["rules"] < 1.0                  # P1 has twi 17: wet enough for the high-TWI rule (and winterkill)
    assert cs["corn"]["parts"]["rules"] < 1.0 < cs["sorghum"]["parts"]["rules"]                     # chronic dry Julys: corn penalty, sorghum bonus


def test_wet_low_lying_field_penalises_winter_crops(world):
    lina_files(world["incoming"], ids=IDS, **{"terrain.csv": lambda df: df.__setitem__("twi", [5, 5, 5, 5, 5, 16.0])})   # P3 is wet
    run(world)
    wet, dry = analyze("P3"), analyze("P2")
    rules = lambda j, crop: next(c for c in j["crop_suitability"] if c["crop"] == crop)["parts"]["rules"]
    assert rules(wet, "winter_wheat") < rules(dry, "winter_wheat")                                  # the high-TWI rule fired for P3 only


@pytest.mark.skipif(not (ROOT / "data/features/climate_season.parquet").exists(), reason="needs data/ (not in git)")
def test_service_uses_the_files_for_a_sample_table_field(tmp_path, monkeypatch):
    """a field of the 2000-field sample (tables path): derived.parquet is applied"""
    monkeypatch.setenv("ML_MODE", "real")
    monkeypatch.setenv("ML_LINA_DIR", str(tmp_path))
    pd.DataFrame([{"field_id": "191825002125636", "slope_pct": 6.5, "twi": 9.0, "slope_class": "moderate",
                   "smap_julaug_mean": 0.27, "smap_deficit_share": 0.5}]).to_parquet(tmp_path / "derived.parquet", index=False)
    b = {"field": {"field_id": "191825002125636", "centroid": {"lat": 41.81, "lon": -91.0}, "admin": {"state": "IA"}}}
    j = TestClient(app).post("/ml/v1/analyze", json=b).json()
    assert j["feature_source"] == "tables" and {"nasadem", "smap"} <= {s["id"] for s in j["sources"]}
    assert not any("TWI" in w or "SMAP" in w or "NASADEM" in w for w in j["warnings"])
    assert any("NASADEM" in e["source_ids"] or "nasadem" in e["source_ids"] for s in j["strategies"][1:] for e in s["evidence"])


# ---------------------------------------------------------------- Lina's real GEE output formats (ml/gee/*.py)

HER_YEARS = range(2015, 2026)             # her scripts start in 2015


def her_files(incoming: Path, ids=IDS, deg=None):
    """hls_ndvi_monthly_long.csv, smap_monthly_long.csv and terrain2.csv exactly as the notebooks write them (no twi)"""
    incoming.mkdir(exist_ok=True)
    rng = np.random.default_rng(5)
    ndvi = [(f, f"{y}-{m:02d}", y, m, round(float(np.clip(0.2 + 0.6 * np.exp(-((m - 7.5) ** 2) / 4) + rng.normal(0, 0.02), -1, 1)), 4), 4)
            for f in ids for y in HER_YEARS for m in range(4, 11)]
    smap = [(f, f"{y}-{m:02d}", y, m, round(float(0.3 + rng.normal(0, 0.02) - (0.15 if f == "P1" and y % 2 == 0 else 0)), 3))
            for f in ids for y in HER_YEARS for m in (6, 7, 8)]
    deg = deg or [1.0 + 0.5 * i for i in range(len(ids))]
    terrain = [(f, d, round(d * 1.4, 2), round(d * 1.8, 2)) for f, d in zip(ids, deg)]
    pd.DataFrame(ndvi, columns=["field_id", "date", "year", "month", "ndvi_hls", "n_obs"]).to_csv(incoming / "hls_ndvi_monthly_long.csv", index=False)
    pd.DataFrame(smap, columns=["field_id", "date", "year", "month", "smap_rootzone"]).to_csv(incoming / "smap_monthly_long.csv", index=False)
    pd.DataFrame(terrain, columns=["field_id", "slope_deg", "slope_deg_p75", "slope_deg_p90"]).to_csv(incoming / "terrain2.csv", index=False)
    return terrain


def test_her_files_are_converted_and_installed(world):
    terrain = her_files(world["incoming"])
    assert run(world) == 0
    ndvi = pd.read_csv(world["lina"] / "ndvi_monthly.csv", dtype={"field_id": str})
    assert list(ndvi.columns) == ["field_id", "year", "month", "ndvi_mean", "n_obs"] and ndvi["year"].min() == 2015       # ndvi_hls renamed, date dropped, 2015 kept
    smap = pd.read_csv(world["lina"] / "smap_monthly.csv", dtype={"field_id": str})
    assert list(smap.columns) == ["field_id", "year", "month", "smap_rootzone"] and smap["year"].min() == 2015
    t = pd.read_csv(world["lina"] / "terrain.csv", dtype={"field_id": str}).set_index("field_id")
    f, deg, deg75, deg90 = terrain[3]
    assert t.loc[f, "slope_pct"] == pytest.approx(np.tan(np.radians(deg)) * 100, abs=0.01)                                # percent, not degrees
    assert t.loc[f, "slope_pct_p75"] == pytest.approx(np.tan(np.radians(deg75)) * 100, abs=0.01)
    assert t.loc[f, "slope_pct_p90"] == pytest.approx(np.tan(np.radians(deg90)) * 100, abs=0.01) and "twi" not in t.columns
    county = pd.read_parquet(world["pre"] / "19153.parquet").set_index("field_id")
    assert county.loc["P2", "slope_pct"] == pytest.approx(np.tan(np.radians(terrain[4][1])) * 100, abs=0.01)
    assert county["twi"].isna().all() and county["smap_deficit_share"].notna().all()                                       # no TWI in her file
    assert county.loc["P1", "smap_deficit_share"] >= 0.4                                                                   # 11 years: the dry Julys of P1 show


def test_impossible_slopes_in_her_file_are_dropped(world):
    deg = [1.0, 2.0, 3.0, 90.0, -1.0, float("nan")]                      # 90 -> infinite percent, negative, empty
    her_files(world["incoming"], deg=deg)
    assert run(world) == 1                                               # 3 of 6 bad is over 5%: terrain is refused (exit code 1) ...
    assert not (world["lina"] / "terrain.csv").exists()
    assert run(world, "--max-bad-share", "0.6") == 0                     # ... unless the limit is raised: the bad rows are then dropped
    pct = pd.read_csv(world["lina"] / "terrain.csv")["slope_pct"]
    assert pct.between(0, 100).all() and len(pct) == 3


def test_field_without_slope_falls_back_to_ssurgo(world):
    deg = [1.0, 2.0, 3.0, 4.0, 5.0, float("nan")]
    her_files(world["incoming"], deg=deg)
    assert run(world, "--max-bad-share", "0.5") == 0
    county = pd.read_parquet(world["pre"] / "19153.parquet").set_index("field_id")
    gap = county.index[county["slope_pct"].isna()]
    assert len(gap) >= 1                                                  # the field without NASADEM slope keeps no NASADEM value ...
    f = next(i for i in gap if not pd.isna(county.loc[i, "slope_r"]))
    out = analyze(f)
    assert "nasadem" not in {s["id"] for s in out["sources"]} and out["strategies"]    # ... and the service still answers, on the SSURGO slope


def test_service_with_her_files_twi_missing_is_only_a_warning(world):
    her_files(world["incoming"])
    run(world)
    after = analyze("P1")
    assert {"nasadem", "smap", "landsat_ndvi"} <= {s["id"] for s in after["sources"]}
    text = " ".join(after["warnings"])
    assert "NDVI" not in text and "SMAP" not in text and "TWI" in text and after["status"] == "ok"     # the TWI rule is off and it is said, but that alone is not "partial"
    cs = {c["crop"]: c for c in after["crop_suitability"]}
    assert cs["corn"]["parts"]["rules"] < 1.0 < cs["sorghum"]["parts"]["rules"]                              # SMAP still drives the dry-July rules


def test_merge_adds_a_second_field_set(world):
    her_files(world["incoming"], ids=SAMPLE)
    assert run(world) == 0
    second = world["tmp"] / "incoming2"
    her_files(second, ids=COUNTY)
    world["incoming"] = second
    assert run(world, "--merge") == 0
    t = pd.read_csv(world["lina"] / "terrain.csv", dtype={"field_id": str})
    assert sorted(t["field_id"]) == sorted(IDS)                                                              # both sets, nothing lost
    assert pd.read_csv(world["lina"] / "ndvi_monthly.csv", dtype={"field_id": str})["field_id"].nunique() == 6
    assert set(pd.read_parquet(world["lina"] / "derived.parquet")["field_id"]) == set(IDS)
    run(world)                                                                                               # without --merge the second set replaces the first
    assert sorted(pd.read_csv(world["lina"] / "terrain.csv", dtype={"field_id": str})["field_id"]) == sorted(COUNTY)
