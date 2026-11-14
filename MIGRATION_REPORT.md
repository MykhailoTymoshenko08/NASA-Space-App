# Migration report: CSB field polygons for IA, IL, NE (contract 0.3.0)

Branch: `migrate/csb-3-states`. Status: backend + contract done (2026-11-14); frontend not in this repo.

## Scope actually done in this repo

- This repo holds `/contract` and `/backend` only. There is no `/frontend` here, so section 5 of the
  migration prompt (frontend PMTiles source, wording, MSW mocks, Playwright) is **not done here**. The
  frontend work needed is listed under "Frontend handoff" below.
- `BACKEND_PROMPT.md`, `FRONTEND_PROMPT.md`, `BACKEND_UPDATE_0.2.0.md` are not in the repo (they only
  exist outside it), so nothing was moved to `docs/archive/` or deleted. `FRONTEND_UPDATE_0.2.0.md`
  does not exist.
- Hosting: built and verified against a local Range + CORS static server only. R2/S3 upload steps are
  documented in `backend/README.md` for a human to run (no credentials or upload tooling here).

## 1. Inventory (written before any deletion)

Grep over the repo (excluding `.git`, `backend/data/`, `uv.lock`) for `plss`, `PLSS`, `FRSTDIV`,
`township`, `section`, `sections.parquet`, the XYZ field tile code and pilot-region CSB code.
Hits of "section" meaning a document section were ignored.

### Delete (becomes unused with 0.3.0)

| File | Size (bytes) | Why it is unused |
|---|---:|---|
| `backend/scripts/prepare_plss.py` | 13050 | BLM PLSS download + section/township build. PLSS is dropped. |
| `backend/scripts/prepare_field_data.py` | 9306 | Old pilot-region CSB cut from the Source Cooperative mirror. Already marked UNUSED, and already broken (reads `settings.pilot_counties`, which no longer exists). Replaced by the fixed 3-state import. |
| `backend/scripts/_httpfile.py` | 1932 | HTTP range file object, only imported by `prepare_field_data.py`. |
| `backend/app/geo/fields_index.py` | 3052 | In-memory STRtree over `sections.parquet`. Replaced by PostGIS lookups. |
| `backend/app/geo/tiles.py` (field part) | 2296 (whole file) | `TileSource` stays for boundary tiles; `tile_bbox`/`bbox_intersects` only served the field tile region filter. |
| `backend/app/api/tiles.py` field route | 1659 (whole file) | `GET /tiles/fields/{z}/{x}/{y}.mvt`: field tiles become a static PMTiles file. Boundary route stays. |
| `backend/tests/test_real_data.py` | 2349 | Asserts PLSS sections (`plss:` ids, `label`, `plss_section`). Rewritten for CSB, not kept as is. |
| PLSS parts of `backend/tests/test_geo_fields.py`, `fixture_data.py`, `test_snapshots.py`, `test_analyses.py`, `test_locations.py`, `test_hardening.py` | n/a | PLSS fixture ids, `plss` / `label` assertions, field tile tests. Rewritten for CSB. |
| PLSS parts of `app/models.py` (`PlssRef`, `FieldSelection.plss`, `.label`, `BoundaryType.plss_section`) | n/a | Removed from contract 0.3.0. |
| PLSS parts of `app/services.py`, `app/geo/coverage.py`, `app/geo/resolve.py`, `app/geo/boundaries.py`, `app/core/config.py` (`plss_states`) | n/a | Replaced by PostGIS field store and 3-state coverage. |
| `townships` layer in `scripts/prepare_boundaries.py` | n/a | Boundary tiles keep `states`, `counties` only. |
| `PLSS_STATES` in `backend/.env.example`, `data-plss` target in `Makefile`, PLSS file checks in `Dockerfile`, PLSS sections in `backend/README.md` and `backend/data/README.md` | n/a | Config and docs for removed code. |
| PLSS wording in `app/analyses/stub.py`, `app/data_sources/ssurgo.py` | n/a | Wording only; the area-weighting logic stays and now applies to CSB polygons. |

### Large local data (gitignored, `backend/data/`)

| Path | Size | Action |
|---|---:|---|
| `data/raw/plss/` | 68 MB | delete (BLM page cache) |
| `data/sections.parquet` | 19 MB | delete |
| `data/townships.parquet` | 4.3 MB | delete |
| `data/plss_meta.json` | 4 KB | delete |
| `data/fields.pmtiles` (PLSS sections) | 33 MB | delete (replaced by `csb_ia_il_ne.pmtiles`, served outside the backend) |
| `data/boundaries.pmtiles` | 6.8 MB | rebuild without `townships` |

### Keep

`CONTRACT_CHANGELOG.md` history, analysis stub, snapshot data sources, `buffered_point` fallback,
geo endpoints, location parser, boundary tiles (`states`, `counties`), tests that still apply.

## 2. What was deleted or changed

| Commit | Change |
|---|---|
| `94d92ff` | Contract 0.3.0 + changelog + regenerated `openapi.json`; this inventory |
| `eef7cc5` | Backend on PostGIS (`app/geo/field_store.py`); `/tiles/fields/...` route and its `tile_bbox`/`bbox_intersects` helpers removed; `PlssRef`, `plss`, `label`, `plss_section` removed from models; `PLSS_STATES`, `field_tiles_min/max_zoom` settings removed; townships layer removed from `prepare_boundaries.py`; PLSS wording in stub/SSURGO replaced; tests rewritten (scratch PostGIS DB) |
| `cd3e810` | Deleted `scripts/prepare_plss.py`, `app/geo/fields_index.py` |
| `36b2ca3` | Deleted `scripts/prepare_field_data.py`, `scripts/_httpfile.py` |
| `23b3d86` | Added `scripts/prepare_csb.py`; README, `data/README.md`, CI (PostGIS service), real-data tests rewritten for CSB |
| `b11ea1c` | Export fix; real numbers in README |

Backend tests and lint ran after each batch (186 passed each time; 189 incl. real-data tests after the import).

Local data deleted (gitignored): `data/raw/plss/` (68 MB), `sections.parquet` (19 MB), `townships.parquet`
(4.3 MB), `plss_meta.json`, PLSS `fields.pmtiles` (33 MB). `boundaries.pmtiles` rebuilt without
townships (6.7 MB). Added: `data/raw/csb/NationalCSB_2018-2025_rev23.zip` (3.76 GB, can be deleted
after import), `data/csb_ia_il_ne.pmtiles` (540 MB).

## 3. Real numbers

| Item | Value |
|---|---|
| Source | NASS `NationalCSB_2018-2025_rev23.zip`, 3,758,023,527 bytes (under the 15 GB limit). FileGDB layer `national1825`, 15,973,095 polygons nationwide, CRS = EPSG:5070 parameters |
| Polygons IA + IL + NE | 1,784,509 (IL 587,831; IA 628,672; NE 568,006), under the 6M limit. 0 empty after `ST_MakeValid`; 190 MultiPolygons |
| Crop history rows | 14,276,072 (8 years 2018-2025 for every polygon) |
| Import | 730 s. PostGIS DB 3.2 GB |
| PMTiles | 539,948,783 bytes (0.54 GB, under the 5 GB limit), z11-14, built at the first try (min zoom 11) in 386 s; a decode of all z11 tiles found all 1,784,509 `field_id`s |
| Largest sample z11 tiles | about 45 KB (Ames IA: 904 fields), far below the 500 KB limit |

## 4. Crop-history decision

The NASS original has `CDL2018`..`CDL2025` per polygon, so the mirror fallback was not needed. History
is filled for all fields (newest first). Codes map to names with the official CDL 2024 code list
(`backend/scripts/cdl_codes.json`). Codes 0 (background) and 81 (clouds/no data) count as no crop and are
left out; none of the imported polygons lacked a 2025 crop. `options.crop_history` from the farmer
replaces the mapped history in the analysis stub.

## 5. Verification

- `make test`: 211 passed against a scratch PostGIS database. The count includes another agent's
  uncommitted `field_info` tests, see open issues; my suite alone is 189. `-m contract`: 106 passed. The committed
  `openapi.json` matches the committed YAML.
- Real data: `tests/test_real_data.py` (Ames IA field, Austin TX buffered point, 3-state coverage)
  passes.
- PMTiles over HTTP (`make serve-tiles`):
  - `Range: bytes=0-16383` returns 206 with `Content-Range`, `ETag` and
    `Access-Control-Allow-Origin: http://localhost:5173`, and exposes `ETag`.
  - The preflight allows `GET, HEAD` and the `Range` header.
  - Another origin gets no CORS headers. Path traversal returns 404.
  - The Python `pmtiles` reader, reading only via Range requests (27 requests), decoded the header
    (layer `fields`, z11-14) and fetched z11 and z14 tiles with fields in all three states.
- Live API flow (uvicorn + local tile server):
  - Coverage: bounds `[-104.05, 36.97, -87.02, 43.50]`, 3 regions, `format: pmtiles`.
  - Click in Iowa: `estimated_csb`, Corn, 8-year history. A snapshot followed (1.5 s), then an
    analysis that succeeded with the baseline "Continue current rotation: Soybeans / Corn".
  - County pick (Champaign IL): snapped to a field. All 102 IL counties have `has_field_coverage: true`;
    TX counties return 404.
  - Pasted coordinates and a Google Maps URL: both resolve to the same NE field.
  - Texas point: `buffered_point`, Travis County.

## 6. Open issues

- **Frontend not done here** (not in this repo). Needed there:
  - Register `pmtiles` and add the `fields` source from `coverage.field_tiles.url_template` when
    `format === 'pmtiles'`.
  - Delete the XYZ field source and the `townships` layer.
  - Zooms: states below 7, counties 7-10, fields from `min_zoom` (11). Fit to `coverage.bounds`.
  - Outside the 3 states: show a notice and still allow a point selection.
  - Say "estimated field area". Show `crop_class` and `crop_history`, and prefill the "what did you
    grow" form from it.
  - Remove all PLSS wording, fixtures and mocks. Add a small `.pmtiles` fixture for MSW mode.
  - Regenerate API types; run the build and the Playwright test.
- **Production hosting not done**: no R2/S3 credentials or upload tools here. Steps and the CORS policy
  are in `backend/README.md` > "Hosting the field tiles". Range + CORS were verified against the local
  server only; repeat the `curl` check from the README against the R2 URL.
- **Concurrent uncommitted work in this checkout**: another agent added contract 0.3.1
  (`POST /fields/info`, `app/field_info/`, edits to `models.py`, `services.py`, `api/fields.py`, README,
  changelog). It is not part of these commits and was left untouched.
- `.claude/worktrees/auth` (branch `feat/auth`) still contains PLSS code from before this migration.
  It needs a rebase onto this branch.
- The 190 MultiPolygons are returned as one Polygon (the part under the click, else the largest), since
  the contract allows only Polygon. Tiles keep all parts.
- `FIELD_STATES` is a code constant, not an env var, as the decision is fixed for the MVP.
- The NASS server rejects plain GETs of the zip (HTTP 500). `prepare_csb.py` downloads in Range chunks.
