# Migration report: CSB field polygons for IA, IL, NE (contract 0.3.0)

Branch: `migrate/csb-3-states`. Status: in progress.

## Scope actually done in this repo

- This repo holds `/contract` and `/backend` only. There is no `/frontend` here, so section 5 of the
  migration prompt (frontend PMTiles source, wording, MSW mocks, Playwright) is **not done here**. The
  frontend work needed is listed under "Frontend handoff" below.
- `BACKEND_PROMPT.md`, `FRONTEND_PROMPT.md`, `BACKEND_UPDATE_0.2.0.md` are not in the repo (they only
  exist outside it), so nothing was moved to `docs/archive/` or deleted. `FRONTEND_UPDATE_0.2.0.md`
  does not exist.
- Hosting: built and verified against a local Range + CORS static server only. R2/S3 upload steps are
  documented in `backend/README.md` for a human to run (no credentials or upload tooling here).

## 1. Inventory (before deletion)

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
