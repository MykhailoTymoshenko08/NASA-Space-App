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
1. ML model — classifier: how well each candidate crop fits a field, given previous crops, season climate, soil, terrain
2. agro calculator — water use (Kc × ET0, FAO-56), N fixation, bare days, simplified RUSLE erosion
3. ranking — which crop to grow next, then rotations built from the ranking (final plan):
   rules (`config/crop_rules.yaml`) drop forbidden crops with a reason → ML classifier gives each remaining crop
   a score → multiply by predecessor→crop transitions (`config/transition_matrix.yaml`) → top 3 of different
   groups (cereal / legume / other) → rotations. candidates: `config/candidate_crops.yaml`
   model classes: corn, soybean, winter_wheat, sorghum, alfalfa (`model: true`). oats, barley and cereal_rye (cover)
   are rules-only (`rule_score`, no `model_prob`): too rare in the training states (oats 35 rows, barley 2)
   rules and transition values are drafts (TODO sources); calculator + priority sliders (old layer 3) stay for the strategy scores
4. ML service implementing the contract (mock first, then real)

## model plan (final)
- LightGBM multiclass classifier, 5 classes, class weights for imbalance
- table: field × year 2019-2025 (`scripts/04_build_dataset.py`): label = crop this year; features = only what is known
  before sowing: crop 1 and 2 years ago, climate NORMAL of the POWER cell (one fixed mean per field; a leave-one-year-out mean leaks the current season) + previous season's
  weather, soil (SSURGO), slope, location. the weather of the season itself is NOT a feature
- validation: (a) MAIN: grouped by field (fields the model has not seen), (b) leave-one-year-out (same fields).
  metrics top-1/top-3, macro-F1, log-loss; baselines: corn↔soybean alternation, same as last year, state's most common
- the NDVI regression idea (Landsat target, quantiles, SHAP) is parked until Lina's data arrives;
  its dataset script is kept in `scripts/legacy/04_build_ndvi_dataset.py`
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
- organic soils (om_pct > 20, peat / muck) are excluded from training; the service answers `status: partial` + warning "organic soil"

## expected files from Lina (CSV)
- `ndvi_monthly.csv`: field_id, year, month, ndvi_mean, n_obs
- `ndvi_season.csv`: field_id, year, ndvi_peak, ndvi_peak_doy
- `smap_monthly.csv`: field_id, year, month, smap_rootzone
- `terrain.csv`: field_id, slope_pct, twi (NASADEM; slope in percent everywhere, 5° ≈ 8.7%)
  until it arrives, `slope_pct` falls back to SSURGO `slope_r` (and `twi` stays empty)
put them into `data/lina/`

## pipeline
- `scripts/01_sample_csb.py` — sample fields from CSB → `data/fields/` (fields.parquet, crop_history.parquet, fields_for_gee.zip) ✅ written, tested on synthetic data
- `scripts/02_power_climate.py` — POWER climate features → `data/features/` (climate_season.parquet, climate_monthly.parquet) ✅ written, tested with mocked api
- `scripts/03_soil_ssurgo.py` — SSURGO topsoil (0-30 cm) via SDA REST → `data/features/soil.parquet` (clay, sand, om, soc, pH, EC, awc, kw, hydgrp, drainage, texture, slope_r) ✅ run on real api, 2000/2000 fields
- `config/crop_rules.yaml` — agronomic rules + crop parameters from Lina, draft, no loader yet
- `scripts/04_build_dataset.py` — field × year crop table → `data/dataset/crops_train.parquet` (label = crop this year) ✅
- `scripts/03b_winter_tmin.py` — winter minimum temperature per field from the POWER cache → `data/features/winter_tmin.parquet` ✅
- `scripts/05_train.py` — LightGBM crop classifier (no class balancing) + temperature calibration; main check grouped by field → `models/crop_model/` ✅ (top-1 78.2% vs 66.7% for corn↔soy alternation on unseen fields; the gain is in KS/NE, in IA/IL ≈ alternation)
- `scripts/06_calibrate_thresholds.py` — suitability trapezoids (plateau = empirical p10-p90 for crops with >= 100 fields, hard bounds = literature DRAFT; a bias check switches everything to literature if literature-only crops look systematically more suitable) → `config/suitability.yaml`, `config/suitability_check.yaml`, `docs/suitability_literature_vs_real.md` (pitch table)
- `ml_service/ranking.py` (+ `rules.py`, `field_context.py`, `feature_text.py`) — crop ranking: score = hard filters × calibrated model prob × transition (`config/transition_matrix.yaml`, softened: M ** beta, beta = 0.5) × suitability × soft rules; top-3 of different groups; `scripts/07_demo_ranking.py` shows it ✅
  rules-only crops (oats, barley, cereal_rye) get a neutral model value = the field's lowest model probability; cover crops are never offered as a main crop
- `ml_service/rotations.py` (+ `agro.py`, `stress.py`, `season_climate.py`, `config/rotation_settings.yaml`) — rotation planner: current rotation from the CSB history (last 4-8 years), all 3-year chains of unblocked crops scored by the ranking, winter cover (cereal rye) slots, agro calculator (bare days, N balance, Kc × ET0 water, RUSLE erosion, pest cycle), farmer priorities + "fit" → 0-100 + delta, alternatives of different logic (cover / small grains / drought / perennial / other set), scenario sliders recompute the climate from shifted daily POWER data, last-season NDVI stress rule (on when `data/lina/ndvi_monthly.csv` exists; tested on synthetic NDVI); output in the contract's `strategies` format, extra numbers in `details`. `scripts/08_demo_rotations.py` shows it ✅
- the mock service's engine lives in `ml_service/mock_rotations.py` (was `rotations.py`, renamed when the real planner took the name)
- `ml_service/` — FastAPI, mock first

## conventions
- complete, production-quality code with explanatory comments
- comments: English only, lowercase sentence starts, concise and direct, no academic phrasing, standard dashes
- run code after writing it; fix root causes from real errors, no speculative patches
- work in sequential phases and stop after each phase for review
- `data/` is gitignored (large files); never commit data
- metric units, snake_case, WGS84 lat/lon in outputs
