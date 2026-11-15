# Contract changelog

`openapi.yaml` is the source of truth. `openapi.json` is generated from it
(`cd backend && make contract-json`). Every change bumps `info.version` and gets an entry here.

## 0.15.0 (2026-11-15): reliable analysis state and planning context

Additive response/request fields; existing anonymous analysis links remain supported.

- Jobs echo their original `options`; planning labels no longer depend on editable URL parameters.
- Rotation plantings optionally include `year` and `season` (`main` or `cover`). Existing `season_index`
  remains available for older clients and legacy cycle-only results.
- Analysis options accept optional `irrigated` and `has_livestock` farmer confirmations.
- Signed-in jobs are scoped to their creator and return 404 to other callers; guest links remain bearer
  links. Dedupe is scoped to the owner. PostgreSQL-backed jobs and PDF caching survive worker changes.
- Comparison context refreshes stale/incomplete snapshots and retains dated available fallbacks.

## 0.14.0 (2026-11-15): PDF analysis report

Additive.

- `GET /analyses/{job_id}/report.pdf` returns the finished analysis as an A4 PDF attachment rendered by the
  backend (summary, strategy cards, conditions with history charts, datasets and disclaimer), in US units.
- New error code `ANALYSIS_NOT_READY` (409) when the job has not succeeded; `details.status` holds its status.
- The endpoint has its own per-IP rate limit (429 `RATE_LIMITED`).

## 0.13.0 (2026-11-15): complete enterprise-budget API

Breaking access and missing-data changes: `POST /profitability/estimate` now requires a bearer token.
Its `scenarios` and `yield_per_acre` can be null when required inputs have no verified baseline.
Consumers must inspect `status` and `missing_inputs` before displaying a return.

- All `/profitability/*` routes require sign-in and share a per-IP rate limit, with documented 401/429 responses.
- `POST /profitability/rotation` exposes the existing rotation calculator without running ML. Plans are
  bounded to five years, reject duplicate seasons and preserve missing-year and double-crop gaps.
  Optional `horizon_years` preserves trailing missing years. Analysis budgets use the requested horizon,
  even when an upstream plan is shorter; those budgets remain partial.
- `GET /profitability/baselines` returns nine default crop/state estimates with coverage, input gaps and sources.
- Crop estimates accept farmer `yield_per_acre`, ordered `price_overrides`, itemized production-cost
  overrides and optional `area_ha`. A farmer yield and `predicted_yield` cannot accompany each other.
  Zero yield/price is valid; non-finite and contradictory financial inputs are rejected.
- Crop outputs include `status`, `price_source`, `currency`, `area_acres`, `is_illustrative`, sources,
  missing inputs, break-even price/yield and field revenue/cost/profit. Before-land return remains null
  when a farmer total does not identify the land component. Farmer costs make no claim about depreciation.
- Placeholder prices, yields, production costs and rents are never calculated. Iowa winter wheat
  requires farmer inputs. Rotation gaps withhold whole-horizon totals; zero and negative returns remain valid.
- Replace unsourced rents with verified references: Iowa 2025 non-irrigated $274/acre, Illinois 2026
  statewide cropland $261/acre and Nebraska 2026 dryland $168/acre. Each source retains its year and category.
  Rebuilding without `NASS_API_KEY` preserves these pinned references. No credentials are required at runtime.
- Money uses decimal half-up rounding to cents. Field profit subtracts field cost from field revenue.
  Rotation field totals sum yearly cents; annual field averages divide those totals. Per-acre averages
  are rounded independently, so scaling a displayed annual per-acre value can differ by a cent.
- Rotation years identify their yield basis and sources. Field comparisons preserve state-rent provenance,
  withhold unknown inputs and avoid ranking unsourced rents. Invalid comparisons clear any previous deltas.

## 0.12.0 (2026-11-15): field comparisons and area rankings

Additive. Both routes need a bearer token and share a per-client rate limit.

- `POST /comparisons/saved-fields`: 2 to 4 of the user's saved fields side by side, for choosing a field
  to rent. Columns `fields` (A to D) carry rent, an illustrative budget for one shared crop `plan`,
  return after rent, break-even rent, crop history summary, strengths and cautions. `rows` are ready to
  render: unit, `better` (higher / lower / target / none), per-field `cells`, the `best` field ids and
  `same_for_all`. Asking rents (`rent_per_acre`) replace the state reference rent per field.
- `POST /comparisons/area`: filter, sort (soil productivity, size, distance) and page every CSB field
  of a county, a box or a township outline, with percentiles among the matching fields, quartiles and
  `pinned` fields. Soil ratings fill in the background (`soil.status: filling`, then `complete`).
- New snapshot metric `soil_productivity_nccpi` (SSURGO NCCPI v3.0, 0-100, `estimated`), area-weighted
  over the field area. It also appears in `AnalysisResult.current_conditions`.
- New schemas: `SavedFieldComparisonRequest`, `ComparisonPlan`, `FieldComparison`, `ComparedField`,
  `ComparisonRow`, `ComparisonCell`, `ComparisonBest`, `RentUsed`, `ValueRange`, `CropHistorySummary`,
  `CountyRef`, `AreaRankingRequest`, `AreaRanking`, `RankedField`, `Quartiles`.

## 0.11.0 (2026-11-15): profitability input audit

- Default reference yields now match the production-cost enterprise budget, avoiding the combination
  of high-productivity Illinois costs with lower statewide yields and dryland Nebraska costs with
  mixed irrigated/dryland state yields. Independent NASS yields remain the fallback with farmer total costs.
- Published corn-after-soybeans cost/yield profiles replace the universal corn-after-corn minus one
  nitrogen credit shortcut. Illinois soybean-after-soybean budgets are also distinguished. Rotation
  profiles include their existing effects, without a second nitrogen discount.
- `ProfitEstimate.yield_source` adds `budget_reference`; cost lines add `baseline_rotation`.
  `cost_profile` documents the selected enterprise. Existing farmer/model yield and cost overrides remain.
- The $99.85 program-schedule cover cost is no longer applied automatically. Local incremental cover
  costs are required; unknown costs yield an incomplete budget. A separately labeled farm-survey
  direct-cost benchmark is informational and is never substituted as an all-in production cost.
- Budgets show return before land and per-crop break-even prices. The UI distinguishes full modeled
  production returns from cash flow, and historical price sensitivity from forecasts. Losses remain losses.

## 0.10.0 (2026-11-15): rough budgets for ML rotations

- `AnalysisRequest.options.budget` accepts annual land rent, cost per cover planting, and per-crop
  revenue/cost overrides. Changed assumptions participate in normal analysis job deduplication.
- ML strategies gain an optional `budget`: year-by-year costs and low/base/high revenues, average
  annual profit, undiscounted horizon totals, estimated field totals and paired differences from current.
- ML selects crops; backend state baselines supply cash figures. ML income scores never become dollar
  multipliers or yield predictions. Budgeting does not change agronomic strategy scores or ranking.
- Land is charged once per year; cover sowing and termination cost extra with no harvested revenue.
  State baseline corn after soybeans receives the existing nitrogen credit, using actual prior history
  in year one. Farmer production totals are not discounted again.
- Missing crop, rent or double-crop budgets produce explicit gaps and null full-horizon aggregates.
  Estimates are always illustrative; placeholders and out-of-state reference costs are flagged.

## 0.9.0 (2026-11-15): real ML analysis integration

- Existing asynchronous `/analyses` jobs now use the ML service by default. Field IDs, crop history
  and farmer priorities are translated at the backend boundary; frontend request shapes stay unchanged.
- `AnalysisResult.ml_analysis` optionally contains the original ML response, including crop suitability,
  monthly vulnerability, summary, quantitative metrics, confidence and source references.
- Strategies remain sorted by score and include exactly one current rotation. The minimum count is
  relaxed from three to one: agronomic constraints can leave fewer valid alternatives. No strategies
  or unsupported criterion scores are invented to fill the result.
- `horizon_years` is forwarded to the ML planner. Income remains a relative index, not a profit estimate.
- Failed jobs preserve meaningful validation, coverage and upstream-data error codes; transient failures
  include retry guidance. A partial ML result remains a successful job with its warnings.

## 0.8.0 (2026-11-14): survey townships and sections

Additive.

- `GET /tiles/plss/{z}/{x}/{y}.mvt`: PLSS survey townships (about 6 x 6 miles, labelled `T84N R23W`
  plus the civil township name where there is one) and their 36 sections, in the field states.
  Layers `townships`, `township_labels`, `sections`, `section_labels`. Built by
  `backend/scripts/prepare_plss.py` from BLM National PLSS CadNSDI and Census TIGERweb.
  `204` when the server has no PLSS data.

## 0.7.0 (2026-11-14): password change and recovery

- `POST /auth/change-password`: bearer auth plus current password; returns 204.
- `POST /auth/forgot-password`: generic 202 for known and unknown accounts; sends a one-hour,
  single-use reset link through Brevo SMTP, limited to one email per account per minute.
- `POST /auth/reset-password`: token and new password; returns 204, or 422 for an invalid/expired token.
- Password changes and resets revoke all access tokens, refresh tokens and outstanding reset links.
  The client must sign in again. Existing JWTs without a session version remain valid until the first
  password update (or their normal expiry). New unauthorized reason: `session_revoked`.
- New request schemas: `ChangePasswordRequest`, `ForgotPasswordRequest`, `ResetPasswordRequest`.

## 0.6.1 (2026-11-14): sourced profitability baseline

No schema change.

- Baseline numbers for `POST /profitability/estimate` now come from USDA NASS and 2026 extension crop
  budgets (`backend/app/profitability/baseline_data.json`, built by `scripts/build_profit_baseline.py`).
- Prices are now per crop and state, not per crop.
- `baseline.is_placeholder` is now per estimate: true only when a number this estimate used is still a
  placeholder (Iowa winter wheat, land rent until a NASS Quick Stats key is used).

## 0.6.0 (2026-11-14): saved fields per user

Additive. All new routes need `Authorization: Bearer`.

- New tag `saved-fields`: `GET`/`POST /me/fields`, `GET`/`PATCH`/`DELETE /me/fields/{saved_field_id}`,
  `POST /me/fields/{saved_field_id}/refresh-info`. Under `/me` because `/fields/{field_id}` is the CSB lookup.
- A saved field stores the user's name, the GeoJSON Polygon or Point, the CSB `field_id` if any, derived
  `centroid`, `area_ha` and `state` (IA/IL/NE), optional farmer `crop_history`, and a `/fields/info`
  snapshot (`info`, `info_fetched_at`) fetched on create and on `refresh-info`.
- Another user's field, or a malformed id, is `404 NOT_FOUND`. Delete is permanent.
- Cap per user (default 50, `SavedFieldList.limit`): new error code `FIELD_LIMIT_REACHED` (409).
- New schemas `SavedField`, `SavedFieldList`, `SavedFieldCreate`, `SavedFieldUpdate`, `SavedCropYear`.

## 0.5.0 (2026-11-14): profitability estimate

Additive.

- New tag `profitability`: `POST /profitability/estimate`. Synchronous profit per acre
  (yield x price - costs) at a low, base and high price for Corn, Soybeans or Winter Wheat in IA, IL or NE.
- Yield is the optional `predicted_yield` from the ML model, else a baseline default per crop and state.
  Prices and costs come from static baseline tables; no price forecast and no external calls.
- Optional `cost_overrides`: `land_rent_per_acre` replaces the baseline rent; `total_cost_per_acre`
  replaces all costs. Corn with `previous_crop: Soybeans` gets a nitrogen credit on fertilizer.
- Response carries the cost lines, the three scenarios, plain-English `assumptions` and
  `baseline.is_placeholder` (true until the tables hold real USDA numbers).
- New schemas `ProfitCrop`, `ProfitState`, `ProfitEstimateRequest`, `ProfitEstimate`, `ProfitScenario`,
  `ProfitCostItem`.

## 0.4.2 (2026-11-14): audit fixes for validation and slow data sources

Additive contract correction; existing response shapes are unchanged.

- Document `422 ValidationError` for malformed state/county FIPS and invalid boundary tile coordinates.
- Field context keeps slow source fetches running for up to 60 seconds, shares pending requests,
  and caches successful results for subsequent calls instead of cancelling at the response deadline.
- USGS terrain and SoilGrids nitrogen queries allow slow replies and retry one transient transport
  failure or HTTP 502/503/504. Snapshot background work has the same 60-second upper bound.

## 0.4.1 (2026-11-14): backend serves the field PMTiles file

Additive. (Prepared on a parallel branch as 0.3.2; renumbered when merged after 0.4.0.)

- New `GET`/`HEAD /tiles/fields.pmtiles`: the whole field PMTiles archive with HTTP Range support
  (206 + `Content-Range`, `ETag`, 416 for bad ranges, 404 when not prepared). CORS allows `HEAD` and
  exposes `ETag`, `Content-Range`, `Content-Length`.
- `coverage.field_tiles.url_template` is by default the absolute URL of that path on the backend; a
  deployment may still point it at external static hosting. The frontend keeps reading the URL from
  coverage, so nothing changes there.

## 0.4.0 (2026-11-14): email + password accounts

Additive, not breaking. No existing endpoint requires auth yet.

- New tag `auth`: `POST /auth/register` (201), `POST /auth/login`, `POST /auth/refresh`,
  `POST /auth/logout` (204), `GET /me`.
- Register, login and refresh return `AuthTokens` (`access_token` JWT, `token_type: bearer`,
  `expires_in` seconds, `user`) and set the `refresh_token` httpOnly cookie on path `/v1/auth`.
  Refresh reads that cookie and rotates it (single use).
- `bearerAuth` security scheme; `GET /me` uses it.
- New schemas `RegisterRequest`, `LoginRequest`, `User`, `AuthTokens`; new responses `Unauthorized`
  (401, `WWW-Authenticate: Bearer`, `details.reason`) and `ValidationError`.
- `ErrorCode` gains `UNAUTHORIZED` (401) and `EMAIL_TAKEN` (409).

## 0.3.1 (2026-11-14): farmer-facing field context

Additive: `POST /fields/info` takes the existing `{point: {lat, lon}}` map payload and returns
`FieldInfo` with labeled, unit-bearing metrics. Coverage is IA/IL/NE bounding boxes only (422 outside).
NASA POWER monthly/climatology, SSURGO point soil, USGS 3DEP elevation/estimated slope, and 2024
Annual NLCD are fetched concurrently with independent failure handling and an in-memory source cache.
This endpoint is independent of the snapshots used by analyses. No existing response changes.

## 0.3.0 (2026-11-14): CSB field polygons for IA, IL, NE; PLSS removed

Breaking. The selectable unit is again an **estimated field area** from USDA Crop Sequence Boundaries
(CSB), now only for Iowa, Illinois and Nebraska. PLSS sections (0.2.0) are removed. Elsewhere in CONUS a
point resolves to a buffered point, as before.

- `FieldSelection`:
  - `boundary_type` enum is `[estimated_csb, buffered_point]`. `plss_section` is removed.
  - `plss` (`PlssRef`) and `label` are removed. `PlssRef` schema is removed.
  - `crop_class` (latest CDL crop name) and `crop_history` (`[{year, crop}]`, newest first, up to 8 years)
    are filled from CSB again. Empty for buffered points.
- `FieldId` is `csb<edition>_<CSBID>` (e.g. `csb2025_190000123456`); the CSB id is only unique within
  one edition.
- `GET /tiles/fields/{z}/{x}/{y}.mvt` is removed. Field polygons are one static PMTiles file hosted
  outside the backend.
- `Coverage`:
  - `bounds` is the bbox of the supported states; `supported_states` is `["IA","IL","NE"]`.
  - `field_tiles.format` (new, required, `pmtiles`); `field_tiles.unit` enum is `[estimated_csb]`;
    `url_template` is the absolute URL of the `.pmtiles` file (source layer `fields`, props `field_id`,
    `crop_class`, `area_ha`); `regions` are the three states.
  - `field_boundary_source.boundary_type` enum is `[estimated_csb]`.
- `GET /geo/states` lists only the supported states. `GET /geo/states/{fips}/counties` returns
  `404 NOT_FOUND` for any other state; listed counties all have `has_field_coverage: true`.
- Boundary tiles lose the `townships` layer (`states`, `counties` only).
- `AnalysisRequest.options.crop_history` stays: an optional farmer correction that replaces the mapped
  history.

## 0.2.1 (2026-11-14)

Additive only. These two items were in the backend's earlier 0.2.0 draft and were left out of the
team's PLSS 0.2.0 file.

- `POST /locations/resolve` documents `429 RATE_LIMITED` (with `Retry-After`), like `POST /analyses`.
  Both endpoints are rate-limited per client IP.
- `Metric.unit` documents `fraction` (0 to 1). `Metric.key` documents `soil_wetness_surface` and
  `soil_wetness_rootzone`: NASA POWER modeled soil wetness, unit `fraction`. They are modeled, not
  satellite-measured, so they are separate from the SMAP keys `soil_moisture_*` (`m3/m3`).

## 0.2.0 (2026-11-14): PLSS sections replace crop field polygons

The selectable unit is now a BLM PLSS survey section (about 1 square mile / 640 acres), not a farm
field. API names (`/fields`, `field_id`, `FieldSelection`) are unchanged: "field" now means
"selectable land unit". The UI must say "survey section".

- `FieldSelection`:
  - new required `boundary_type`: `plss_section`, `buffered_point`, or (reserved) `estimated_csb`.
  - new `plss` (`PlssRef`: `township_id`, `section_id`, `section_number`, `division_type`); null for
    buffered points.
  - new `label`, e.g. "Section 14, T80N R24W"; null for buffered points.
  - `crop_class` is always null and `crop_history` always `[]`: PLSS has no crop data.
- `FieldId` is `plss:` + BLM First Division id (+ `-<dup>` suffix when BLM marks a duplicate).
- `Coverage`:
  - `field_boundary_source` is now required: `{name, edition, boundary_type, attribution}`.
  - `field_tiles.unit` is required (`plss_section`).
  - `regions` lists the areas that actually have PLSS data, not all of CONUS.
- `County.has_field_coverage` is true when the county intersects at least one section.
- Tiles: `fields` features are sections with `label`; `crop_class` is an empty string.
  Boundary tiles gain a `townships` layer (`township_id`, `label`) for zoom 8 to 10.
- `AnalysisRequest.options.crop_history` is the only crop history source.

## 0.1.0

Initial contract.
