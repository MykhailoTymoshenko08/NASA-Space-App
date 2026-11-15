# API contract: ML service ↔ Backend ↔ Frontend (v1)

Frontend → Backend → ML service. Frontend never calls ML directly. Backend proxies analysis and returns the ML JSON unchanged (may add `cached: true`).
ML service is stateless: field + priorities in, analysis out. No users, sessions or field db in ML.

## conventions
| what | rule |
|---|---|
| format | JSON, snake_case |
| coordinates | WGS84 (EPSG:4326); GeoJSON order is [lon, lat]; `centroid` uses explicit `lat` / `lon` |
| units | metric: ha, mm, °C, kg/ha, t/ha/yr |
| months | 1-12 |
| scores | 0-100, higher = better for the farmer (risks inverted: 100 = lowest risk) |
| probabilities | 0.0-1.0 |
| crops | `crop` slug (`corn`, `soybean`, `winter_wheat`, `cereal_rye`, `alfalfa`…) + `cdl_code` (USDA CDL code) |
| versioning | `/ml/v1` prefix, `model_version` in every response |
| latency | ML target < 5 s for demo-region fields; backend timeout 30 s |
| text language | `options.language`: `en` (default) or `uk` |
| field_id | CSB `CSBID` string |

> **v1.1 (additive).** The real service adds optional fields to `/ml/v1/analyze`; every v1 field is unchanged, so old clients keep working:
> `crop_suitability`, `score_notes`, `feature_source`, `detected_rotation.cycle_years`, `vulnerability_timeline[].bare_soil_source`, `/ml/health.mode`.
> `ML_MODE=mock` keeps the old contract-shaped mock (without the new fields); `ML_MODE=real` is the default.

## GET /ml/health
```json
{ "status": "ok", "model_version": "0.2.0", "mode": "real", "coverage": { "states": ["IA", "IL", "NE", "KS"], "years": [2018, 2025] } }
```

## GET /ml/v1/meta/crops
```json
{ "crops": [
  { "crop": "corn", "cdl_code": 1, "name_en": "Corn", "name_uk": "Кукурудза", "type": "cash" },
  { "crop": "soybean", "cdl_code": 5, "name_en": "Soybeans", "name_uk": "Соя", "type": "legume" },
  { "crop": "cereal_rye", "cdl_code": 27, "name_en": "Cereal rye", "name_uk": "Жито (покривна)", "type": "cover" }
] }
```

## POST /ml/v1/analyze

### request
```json
{
  "request_id": "b1f2c3d4-...",
  "field": {
    "field_id": "191825000000212",
    "geometry": { "type": "Polygon", "coordinates": [[[-93.62, 41.59], [-93.61, 41.59], [-93.61, 41.60], [-93.62, 41.60], [-93.62, 41.59]]] },
    "centroid": { "lat": 41.595, "lon": -93.615 },
    "area_ha": 64.7,
    "admin": { "country": "US", "state": "IA", "state_fips": "19", "county_fips": "19153" },
    "crop_history": [
      { "year": 2024, "crop": "corn", "cdl_code": 1 },
      { "year": 2025, "crop": "soybean", "cdl_code": 5 }
    ],
    "soil": { "texture": "silty clay loam", "organic_matter_pct": 3.4, "drainage_class": "poorly drained",
              "hydrologic_group": "C/D", "awc_cm_cm": 0.21, "slope_pct": 2.1 }
  },
  "priorities": { "water": 0.8, "soil_health": 0.6, "nitrogen": 0.5, "erosion": 0.4, "income": 0.7 },
  "scenario": { "temp_delta_c": 0.0, "precip_change_pct": 0 },
  "farmer_input": { "irrigated": null, "current_rotation": null, "excluded_crops": [], "has_livestock": null },
  "options": { "n_strategies": 3, "language": "en", "include_monthly_series": false }
}
```
rules:
- required: `field.field_id`, `field.geometry` (or at least `centroid`), `field.admin.state`
- `crop_history`, `soil` optional - if missing, ML uses its own precomputed data
- `priorities` 0.0-1.0, default 0.5 each
- `scenario.temp_delta_c` in -2..+4, `scenario.precip_change_pct` in -40..+20, default 0/0
- `farmer_input` all nullable; `null` = "detect yourself"; `current_rotation` overrides detection
- `n_strategies` = alternatives, not counting the current one (current is always returned)

### response 200
```json
{
  "request_id": "b1f2c3d4-...",
  "field_id": "191825000000212",
  "model_version": "0.1.0",
  "generated_at": "2026-11-14T15:02:11Z",
  "status": "ok",
  "detected_rotation": { "sequence": ["corn", "soybean"], "label": "Corn – Soybean (2-year)", "confidence": 0.88, "years_used": [2018, 2025], "source": "csb", "cycle_years": 2 },
  "summary": {
    "headline": "Field is bare ~150 days/year and short on moisture in July–August.",
    "overall_risk": "medium",
    "key_numbers": [
      { "id": "bare_days", "label": "Bare soil days / year", "value": 152, "unit": "days", "source_ids": ["landsat_ndvi"] },
      { "id": "jul_aug_moisture_anomaly", "label": "Jul–Aug soil moisture anomaly", "value": -18, "unit": "%", "source_ids": ["smap"] },
      { "id": "heat_days", "label": "Days > 32°C (avg)", "value": 11, "unit": "days", "source_ids": ["power"] }
    ]
  },
  "vulnerability_timeline": [
    { "month": 1, "bare_soil": 0.95, "moisture_deficit": 0.05, "heat_stress": 0.0, "frost_risk": 0.9, "extreme_precip": 0.05, "flags": ["bare", "frost"],
      "bare_soil_source": "crop_calendar" }
  ],
  "strategies": [
    {
      "id": "current", "is_current": true, "name": "Current: Corn – Soybean",
      "sequence": [ { "year": 1, "season": "main", "crop": "corn" }, { "year": 2, "season": "main", "crop": "soybean" } ],
      "scores": { "water": 52, "soil_health": 40, "nitrogen": 55, "erosion": 38, "income": 78, "overall": 54 },
      "delta_vs_current": null,
      "metrics": { "water_use_mm_yr": 560, "n_fixed_kg_ha_yr": 60, "bare_days_yr": 152, "erosion_t_ha_yr": 6.1 },
      "why": "Baseline detected from 2018–2025 Crop Sequence Boundaries.",
      "evidence": [], "benefits": ["High market value"], "risks": ["Long bare period Nov–Apr increases erosion"],
      "data_gaps": [], "check_with_agronomist": [], "confidence": 0.88
    },
    {
      "id": "s1", "is_current": false, "name": "Corn – Soybean + cereal rye cover",
      "sequence": [ { "year": 1, "season": "main", "crop": "corn" }, { "year": 1, "season": "cover", "crop": "cereal_rye" }, { "year": 2, "season": "main", "crop": "soybean" } ],
      "scores": { "water": 49, "soil_health": 68, "nitrogen": 60, "erosion": 74, "income": 75, "overall": 66 },
      "delta_vs_current": { "water": -3, "soil_health": 28, "nitrogen": 5, "erosion": 36, "income": -3, "overall": 12 },
      "metrics": { "water_use_mm_yr": 590, "n_fixed_kg_ha_yr": 60, "bare_days_yr": 45, "erosion_t_ha_yr": 2.3 },
      "why": "Field is bare Nov–Apr and spring rainfall extremes are frequent; a winter cover closes that gap.",
      "evidence": [ { "text": "NDVI < 0.2 for 152 days/yr on average (2019–2025)", "source_ids": ["landsat_ndvi"] } ],
      "benefits": ["Cuts bare days by ~70%"], "risks": ["Rye uses spring soil moisture in dry years"],
      "data_gaps": ["No field-level irrigation data"], "check_with_agronomist": ["Termination timing before soybean planting"],
      "confidence": 0.71
    }
  ],
  "crop_suitability": [
    { "crop": "corn", "name": "Corn", "group": "cereal", "fit_score": 69.8, "next_year_share": 96.3, "rank": 1, "blocked": false,
      "block_reasons": [], "explanation": "Best choice for next year: it suits the field (fit 70) and follows 'Soybean' well (96% of the advice).",
      "top_factors": ["Last year's crop: Soybean - raises the chance", "Crop two years ago: Corn - raises the chance", "Typical climate of the place: day of last spring frost = 114.4 - raises the chance"],
      "top3_role": "highest score", "model_class": true, "role": null,
      "parts": { "model_prob": 0.958, "model_prob_source": "model", "transition": 1.22, "suitability": 0.97, "rules": 1.0, "score_raw": 1.13 } },
    { "crop": "soybean", "name": "Soybean", "group": "legume", "fit_score": 81.2, "next_year_share": 2.6, "rank": 2, "blocked": false,
      "block_reasons": [], "explanation": "Suits the field (fit 81), but last year was already Soybean: repeating the same crop cuts its chance to 3%.",
      "top_factors": [], "top3_role": "best of another group (legumes)", "model_class": true, "role": null, "parts": {} },
    { "crop": "alfalfa", "name": "Alfalfa", "group": "other", "fit_score": 0.0, "next_year_share": 0.0, "rank": 8, "blocked": true,
      "block_reasons": ["soil pH = 5.2: outside the allowed range (5.5–8.5) for this crop"], "explanation": "Excluded: soil pH = 5.2: outside the allowed range (5.5–8.5) for this crop",
      "top_factors": [], "top3_role": null, "model_class": true, "role": null, "parts": {} }
  ],
  "score_notes": { "income": "income_index: a relative 0-100 index of margin, not money" },
  "feature_source": "precomputed",
  "sources": [
    { "id": "landsat_ndvi", "name": "Landsat 8/9 Collection 2 L2 NDVI", "variable": "NDVI", "resolution": "30 m, 8-16 days", "period": "2018–2025" },
    { "id": "smap", "name": "SMAP L4 Global Soil Moisture (SPL4SMGP)", "variable": "root-zone soil moisture", "resolution": "9 km, 3-hourly", "period": "2015–2025" },
    { "id": "power", "name": "NASA POWER AG", "variable": "T2M, T2M_MAX, T2M_MIN, PRECTOTCORR", "resolution": "0.5° × 0.625°, daily", "period": "2017–2025" },
    { "id": "nasadem", "name": "NASADEM 30 m", "variable": "slope, TWI", "resolution": "30 m", "period": "2000" },
    { "id": "csb", "name": "USDA Crop Sequence Boundaries", "variable": "fields + crop history", "resolution": "field, yearly", "period": "2018–2025" },
    { "id": "ssurgo", "name": "USDA NRCS SSURGO", "variable": "soil properties", "resolution": "field-scale map units", "period": "current" }
  ],
  "warnings": [],
  "disclaimer": "Decision-support only. Validate with local agronomic expertise before changing your rotation."
}
```
guarantees:
- `strategies[0]` is always the current rotation, then exactly `n_strategies` alternatives sorted by priority-weighted `scores.overall`
- `vulnerability_timeline` always has 12 items, months 1-12 in order
- `scores` always has all 6 keys
- every `source_ids` value references an `id` in `sources`
- `flags` values: `bare`, `drought`, `heat`, `frost`, `extreme_rain`, `waterlogging`
- `scores.income` is a **relative 0-100 index** of margin (`score_notes.income`), never money
- `crop_suitability` (new): one row per candidate crop, sorted by `rank` (blocked crops last). Two numbers, not one:
  `fit_score` (0-100, absolute) says how well the **field** suits the crop **without** last year's crop: hard filters x suitability trapezoids x soft rules x the calibrated
  model probability averaged over the previous crops that usually precede this crop in the state. A crop that suits the field (soybean on a good field) is high here.
  `next_year_share` (%) is the advice for **next year** with the real previous crop and the transition matrix; it adds up to 100 over the crops that are not blocked
  (a cover crop is not a main crop and gets 0). `rank` follows `next_year_share`. `explanation` says in plain words why a crop with a high `fit_score` may not be
  on top ("suits the field, but last year was already soybean"). `block_reasons` explains why a crop is out (agronomic rules, hard limits of soil and climate, or the farmer's `excluded_crops`).
  `top_factors` are the main reasons for the crop (SHAP groups for crops of the model, the biggest adjustments for rules-only crops: oats, barley, cereal_rye).
  `top3_role` is set for the three crops offered as a main crop (highest score / best of another group / most heat- and drought-tolerant)
- `vulnerability_timeline[].bare_soil_source`: `crop_calendar` (modelled from the crops of the current rotation) or `landsat_ndvi` (when NDVI exists)
- `feature_source`: `precomputed` (county file or the 2000-field sample) or `on_the_fly` (history from the request, soil from USDA SDA, climate from NASA POWER)
- `sources` lists only the sources that were really used
- `overall_risk`: `low` | `medium` | `high`
- `status: "partial"` - analysis exists but some data was missing (no Landsat NDVI, no SMAP, or an organic soil); reasons in `warnings`. A missing TWI or the SSURGO slope instead of NASADEM is only a warning, not `partial`

### errors
```json
{ "error": { "code": "OUT_OF_COVERAGE", "message": "Field is outside the demo region.", "details": {} } }
```
| HTTP | code | when |
|---|---|---|
| 422 | INVALID_INPUT | bad geometry, priorities out of range, etc. In the real mode also: the field is not precomputed and `field.crop_history` is missing; unknown crop in `farmer_input.current_rotation` |
| 404 | OUT_OF_COVERAGE | field outside the region we have data for |
| 503 | DATA_UNAVAILABLE | data source down / not precomputed. In the real mode: the POWER cell of a field outside the precomputed region could not be downloaded in time (it keeps downloading, retry in a minute), or USDA SDA is not reachable |
| 500 | INTERNAL | everything else |

## plan B if analysis gets slow (> 10 s)
`POST /ml/v1/analyze` → `202 { "job_id", "status": "queued" }`, `GET /ml/v1/jobs/{job_id}` → `{ status, result, error }`. start synchronous.
