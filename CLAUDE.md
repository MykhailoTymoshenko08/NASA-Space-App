# FieldShift ML — context for Claude Code

## project
NASA Space Apps Kyiv, Nov 2026, challenge about crop rotation decision support.
Farmer picks a US field on a map → sees detected rotation, a 12-month vulnerability timeline
(bare soil, drought, heat, frost, extreme rain) and 3 alternative rotation strategies vs the current one,
each with scores, reasons, evidence (data sources), risks, data gaps and what to check with an agronomist.
Judges love numbers. The tool supports, not replaces, farmer judgment.

## team
- Mykhailo — AI/ML + integration + team lead (owner of this repo/folder)
- Lina — geospatial / remote sensing; processes satellite data in Google Earth Engine (Landsat 8/9 NDVI, SMAP L4, NASADEM, IMERG)
- Sasha — backend (fields db, proxy to ML)
- Petro — frontend (map, panel, strategy cards)
- Ksenia — PM / UI-UX

## architecture
Frontend → Backend → ML service (FastAPI, this repo). Frontend never calls ML directly.
`field_id` = CSB `CSBID` (unique across editions). ML service is stateless.
Full API contract: `docs/api_contract.md`. Endpoints: `GET /ml/health`, `GET /ml/v1/meta/crops`, `POST /ml/v1/analyze`.

## my scope (ML)
1. ML model — predicts seasonal crop condition for a field given crop sequence, season climate, soil, terrain
2. agro calculator — water use (Kc × ET0, FAO-56), N fixation, bare days, simplified RUSLE erosion
3. ranking — candidate rotations (current, + cover crop, + legume, drought-tolerant, perennial), 3 layers:
   1. filters — agronomic rules from `config/crop_rules.yaml` (Lina): `hard_block` removes a candidate,
      `penalty` / `bonus` shift its scores (soil pH/EC/clay/SOC, slope, TWI, regional GDD, SMAP, precipitation)
   2. ML forecast — LightGBM seasonal crop condition (p10/p50/p90)
   3. calculator + priorities — agro calculator metrics → scores 0-100 → weighted by farmer priority
      sliders → top 3 + explanations
   rules file is a draft (thresholds, points and sources are TODO); nothing loads it yet
4. ML service implementing the contract (mock first, then real)

## model plan
- LightGBM, quantile regression (p10/p50/p90) → `confidence` from interval width
- target: seasonal peak NDVI (Landsat, from Lina) as deviation from the field's own mean
- features: crop this year + previous 1-2 crops (CSB), season climate (NASA POWER), soil (SSURGO), slope + TWI (NASADEM), SMAP anomalies
- validation: leave-one-year-out, compare against baseline (field mean of previous years); report metrics for judges
- explanations: SHAP top features → template text for `why` / `evidence`
- climate scenario sliders: shift temperature / precipitation features, recompute ET0 (Hargreaves) → re-predict

## data decisions (agreed)
- fields + crop history: USDA Crop Sequence Boundaries, edition 2018-2025 (national GDB, Albers EPSG:5070,
  columns CSBID, CSBACRES, CDL2018..CDL2025, STATEFIPS, CNTYFIPS, CNTY, ASD, INSIDE_X, INSIDE_Y)
  download: https://www.nass.usda.gov/Research_and_Science/Crop-Sequence-Boundaries/datasets/NationalCSB_2018-2025_rev23.zip
- training states: Iowa 19, Illinois 17, Nebraska 31, Kansas 20; ~500 fields per state, >= 25 acres, >= 6 crop years
- climate: NASA POWER daily point API (AG community), queried once per 0.5° × 0.625° grid cell
- precipitation for the rules: GPM IMERG (Lina will provide); until then fallback to POWER `precip_grow`
- soil: SSURGO via USDA Soil Data Access REST API (AWC, organic matter → SOC, texture incl. clay %, hydrologic group,
  K factor, drainage, pH, EC/salinity); OpenLandMap as fallback where SSURGO has gaps
- terrain: NASADEM (30 m) from Lina — slope and TWI (topographic wetness index)
- satellite (Lina, via GEE): Landsat 8/9 NDVI, SMAP L4 root-zone soil moisture (9 km — regional context only)
- time step: monthly; spatial: mean of pixels inside the field polygon (coarse products → the pixel containing the field)
- years: 2018-2025 (training seasons need the previous crop, so effectively 2019-2025)

## expected files from Lina (CSV)
- `ndvi_monthly.csv`: field_id, year, month, ndvi_mean, n_obs
- `ndvi_season.csv`: field_id, year, ndvi_peak, ndvi_peak_doy
- `smap_monthly.csv`: field_id, year, month, smap_rootzone
- `terrain.csv`: field_id, slope_pct, twi (NASADEM; slope in percent everywhere, 5° ≈ 8.7%)
put them into `data/lina/`

## pipeline
- `scripts/01_sample_csb.py` — sample fields from CSB → `data/fields/` (fields.parquet, crop_history.parquet, fields_for_gee.zip) ✅ written, tested on synthetic data
- `scripts/02_power_climate.py` — POWER climate features → `data/features/` (climate_season.parquet, climate_monthly.parquet) ✅ written, tested with mocked api
- `scripts/03_soil_ssurgo.py` — next (must also output clay %, SOC, pH, EC for the rules)
- `config/crop_rules.yaml` — agronomic rules + crop parameters from Lina, draft, no loader yet
- `scripts/04_build_dataset.py`, `scripts/05_train.py` — after Lina's NDVI arrives (can start on synthetic target)
- `ml_service/` — FastAPI, mock first

## conventions
- complete, production-quality code with explanatory comments
- comments: English only, lowercase sentence starts, concise and direct, no academic phrasing, standard dashes
- run code after writing it; fix root causes from real errors, no speculative patches
- work in sequential phases and stop after each phase for review
- `data/` is gitignored (large files); never commit data
- metric units, snake_case, WGS84 lat/lon in outputs
