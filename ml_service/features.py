"""Where the features of a field come from.

1. the field is in a precomputed county file (scripts/09_precompute_region.py)      -> read it, no external calls
2. the field is in the 2000-field training tables (data/fields, data/features)       -> read them
3. otherwise, on the fly: history from the request (422 if there is none), soil from USDA SDA at the centroid,
   climate from NASA POWER for the cell (disk cache; a cell that cannot be downloaded in time -> 503)
Then the request's own values (crop history, soil, scenario) are applied on top.
"""
from __future__ import annotations

import dataclasses
import math
from functools import lru_cache

import numpy as np
import pandas as pd

from . import power_client, precomputed, season_climate, soil_sda
from .cdl import history_token
from .errors import invalid_input, out_of_coverage
from .field_context import _tables, load_field_context
from .precomputed import LAST_YEAR
from .ranking import ROOT, Assets, FieldContext

PLAN_YEAR = LAST_YEAR + 1
SOIL_DEFAULTS = {"om_pct": 3.0, "awc_cm_cm": 0.17, "kw_factor": 0.30, "slope_r": 2.0}
DATA_DIR = ROOT / "data"


def _centroid(field) -> tuple[float, float]:
    if field.centroid is not None:
        return field.centroid.lat, field.centroid.lon
    g = field.geometry
    polys = [g.coordinates] if g.type == "Polygon" else g.coordinates
    pts = [p[:2] for poly in polys for p in poly[0]]
    return float(np.mean([p[1] for p in pts])), float(np.mean([p[0] for p in pts]))


def _area_ha(field, lat: float) -> float | None:
    if field.area_ha:
        return float(field.area_ha)
    if field.geometry is None:
        return None
    g = field.geometry
    polys = [g.coordinates] if g.type == "Polygon" else g.coordinates
    ring = polys[0][0]
    kx, ky = 111320 * math.cos(math.radians(lat)), 110540          # metres per degree here
    xs, ys = [p[0] * kx for p in ring], [p[1] * ky for p in ring]
    return abs(sum(xs[i] * ys[(i + 1) % len(ring)] - xs[(i + 1) % len(ring)] * ys[i] for i in range(len(ring)))) / 2 / 10_000


def _history_from_request(items, a: Assets) -> tuple[dict, dict, list[str]]:
    """request crop_history -> (history for the model, rich history for the rotation, warnings)"""
    cdl_to_slug = {c["cdl_code"]: s for s, c in a.candidates.items()}
    hist, rich, unknown = {}, {}, []
    for it in sorted(items, key=lambda i: i.year):
        if it.cdl_code is not None:
            hist[it.year] = cdl_to_slug.get(it.cdl_code, "other")
            rich[it.year] = history_token(it.cdl_code, cdl_to_slug)
        elif it.crop in a.candidates:
            hist[it.year] = rich[it.year] = it.crop
        elif it.crop == "fallow":
            hist[it.year], rich[it.year] = "other", "fallow"
        else:
            hist[it.year] = rich[it.year] = "other"
            unknown.append(it.crop)
    return hist, rich, sorted(set(unknown))


def with_history(ctx: FieldContext, hist: dict, rich: dict, target_year: int) -> FieldContext:
    return dataclasses.replace(ctx, history=hist, history_rich=rich,
                               prev_crops=[hist.get(target_year - 1, "unknown"), hist.get(target_year - 2, "unknown")])


def apply_scenario(ctx: FieldContext, scenario: tuple[float, float]) -> FieldContext:
    """recompute the climate normal from the shifted daily data of the field's cell (last season's weather stays)."""
    if tuple(scenario) == (0.0, 0.0) or ctx.scenario == tuple(scenario):
        return ctx
    clat = float(ctx.cell.split("_")[0])
    daily = season_climate.shift(season_climate.load_daily(str(power_client.cache_dir() / f"{ctx.cell}.json"), clat),
                                 scenario[0], scenario[1], clat)
    n = season_climate.normals(daily)
    monthly = {"et0": n["et0_monthly"], "precip": n["precip_monthly"], "tmean": n["tmean_monthly"], "heat_days_32": n["heat_days_monthly"],
               "frost_days": n["frost_days_monthly"], "extreme_rain_days": n["extreme_rain_days_monthly"]}
    return dataclasses.replace(ctx, climate_norm=n["climate_norm"], winter_tmin_c=n["winter_tmin_c"], et0_monthly=n["et0_monthly"],
                               precip_monthly=n["precip_monthly"], precip_annual=n["precip_annual"], monthly=monthly,
                               scenario=tuple(scenario))


def on_the_fly(req, a: Assets, target_year: int) -> FieldContext:
    f = req.field
    if not f.crop_history:
        raise invalid_input("This field is not in the precomputed region, so field.crop_history is required.",
                            field="field.crop_history", field_id=f.field_id)
    lat, lon = _centroid(f)
    hist, rich, unknown = _history_from_request(f.crop_history, a)
    notes = []
    if unknown:
        notes.append(f"crops not in the catalog were treated as 'other': {', '.join(unknown)}")

    soil = soil_sda.fetch_soil(lat, lon)
    if soil is None:
        soil = {c: None for c in precomputed.SOIL_COLS}
        soil.update({"slope_r": None})
        notes.append("no SSURGO soil at this point (water, urban or outside the survey): regional defaults are used")

    path, clat, cell = power_client.ensure_cell(lat, lon)
    climate = season_climate.field_climate(season_climate.load_daily(str(path), clat), LAST_YEAR)
    monthly = {"et0": climate["et0_monthly"], "precip": climate["precip_monthly"], "tmean": climate["tmean_monthly"],
               "heat_days_32": climate["heat_days_monthly"], "frost_days": climate["frost_days_monthly"],
               "extreme_rain_days": climate["extreme_rain_days_monthly"]}
    ctx = FieldContext(
        field_id=f.field_id, state=f.admin.state, lat=lat, lon=lon, prev_crops=["unknown", "unknown"],
        soil={c: soil.get(c) for c in precomputed.SOIL_COLS}, slope_pct=soil.get("slope_r"),
        climate_norm=climate["climate_norm"], climate_lag1=climate["climate_lag1"], winter_tmin_c=climate["winter_tmin_c"],
        target_year=target_year, et0_monthly=climate["et0_monthly"], precip_monthly=climate["precip_monthly"],
        precip_annual=climate["precip_annual"], monthly=monthly, provenance="on_the_fly", cell=cell,
        area_ha=_area_ha(f, lat), notes=notes)
    return with_history(ctx, hist, rich, target_year)


def apply_request(ctx: FieldContext, req, a: Assets, target_year: int) -> FieldContext:
    """the request's own crop history and soil win over what is stored."""
    f = req.field
    if f.crop_history and ctx.provenance != "on_the_fly":
        hist, rich, unknown = _history_from_request(f.crop_history, a)
        ctx = with_history(ctx, hist, rich, target_year)
        if unknown:
            ctx = dataclasses.replace(ctx, notes=[*ctx.notes, f"crops not in the catalog were treated as 'other': {', '.join(unknown)}"])
    if f.soil is not None:
        s = dict(ctx.soil)
        for src, dst in (("organic_matter_pct", "om_pct"), ("awc_cm_cm", "awc_cm_cm"), ("drainage_class", "drainage_class"),
                         ("hydrologic_group", "hydgrp"), ("texture", "texture_class")):
            v = getattr(f.soil, src)
            if v is not None:
                s[dst] = v
        if f.soil.organic_matter_pct is not None:
            s["soc_pct"] = f.soil.organic_matter_pct / 1.724
        ctx = dataclasses.replace(ctx, soil=s, slope_pct=f.soil.slope_pct if f.soil.slope_pct is not None else ctx.slope_pct)
    if f.area_ha:
        ctx = dataclasses.replace(ctx, area_ha=float(f.area_ha))
    return ctx


def fill_soil_defaults(ctx: FieldContext) -> FieldContext:
    """the calculator needs organic matter, water capacity, erodibility and slope; use regional values when they are missing."""
    soil, notes = dict(ctx.soil), list(ctx.notes)
    missing = []
    for key, default in (("om_pct", SOIL_DEFAULTS["om_pct"]), ("awc_cm_cm", SOIL_DEFAULTS["awc_cm_cm"]), ("kw_factor", SOIL_DEFAULTS["kw_factor"])):
        if soil.get(key) is None or (isinstance(soil.get(key), float) and np.isnan(soil[key])):
            soil[key] = default
            missing.append(key)
    slope = ctx.slope_pct
    if slope is None or (isinstance(slope, float) and np.isnan(slope)):
        slope = SOIL_DEFAULTS["slope_r"]
        missing.append("slope_pct")
    if missing:
        notes.append(f"soil values missing, regional defaults used: {', '.join(missing)}")
    return dataclasses.replace(ctx, soil=soil, slope_pct=float(slope), notes=notes)


def get_context(req, a: Assets, scenario: tuple[float, float], target_year: int = PLAN_YEAR) -> FieldContext:
    state = req.field.admin.state
    from . import COVERAGE_STATES
    if state not in COVERAGE_STATES:
        raise out_of_coverage("Field is outside the demo region.", state=state, covered_states=list(COVERAGE_STATES))
    fid = req.field.field_id
    ctx = precomputed.context(fid, a, target_year)
    try:
        in_tables = fid in _tables(str(DATA_DIR))["fields"].index
    except OSError:                       # no data/ folder: nothing precomputed except county files
        in_tables = False
    if ctx is None and in_tables:
        ctx = load_field_context(fid, a, target_year=target_year)
    if ctx is None:
        ctx = on_the_fly(req, a, target_year)
    ctx = apply_request(ctx, req, a, target_year)       # what the request states wins over what is stored
    ctx = apply_scenario(ctx, scenario)
    return fill_soil_defaults(ctx)
