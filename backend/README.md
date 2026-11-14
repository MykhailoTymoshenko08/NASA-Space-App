# Field Shift backend

FastAPI backend for Field Shift, a NASA Space Apps crop-rotation decision-support tool for US farmers.
It implements `../contract/openapi.yaml` (v0.2.0). The contract is the source of truth; see
`../contract/CONTRACT_CHANGELOG.md` for changes.

## Setup

Requirements:

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 and all dependencies).
- [tippecanoe](https://github.com/felt/tippecanoe) 2.x, only needed to build vector tiles (`make data`).
  - Arch: `yay -S tippecanoe` (AUR)
  - macOS: `brew install tippecanoe`
  - Debian/Ubuntu: build from source (see the tippecanoe README).
- Internet access for `make data` (downloads ~50 MB) and for live snapshot data.

From a fresh clone:

```sh
cd backend
cp .env.example .env      # optional, defaults work
make data                 # boundaries + pilot field polygons + tiles (idempotent)
make dev                  # http://localhost:8000/v1/health, docs at /v1/docs
```

| Command | What it does |
|---|---|
| `make install` | `uv sync` |
| `make dev` | API with auto-reload on `HOST:PORT` (default `127.0.0.1:8000`) |
| `make demo` | install, build data if missing, run the API without reload |
| `make test` | full test suite: no network, no `make data` needed (synthetic fixture data) |
| `make contract-check` | contract tests (real responses validated against the YAML) + `openapi.json` sync check |
| `make contract-json` | regenerate `../contract/openapi.json` from the YAML |
| `make data` / `data-boundaries` / `data-fields` | build `data/`; add `FORCE=1` to rebuild existing outputs |
| `make lint` | ruff |
| `make docker` | build image `field-shift-backend` with `data/` baked in (runs `make data` first if tiles are missing) |

Docker: `make docker`, then `docker run --rm -p 8000:8000 -e FRONTEND_ORIGIN=<frontend url> field-shift-backend`.
The image contains the prepared data (~30 MB), so it needs no tippecanoe or data download at runtime.
Rebuild the image after `make data FORCE=1`.

CI (`.github/workflows/backend.yml`) runs lint, `make contract-check` and `make test`.

## Configuration (env vars)

| Variable | Default | Notes |
|---|---|---|
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS allowed origin |
| `DATA_DIR` | `backend/data` | prepared data (see `data/README.md`) |
| `CACHE_DIR` | `backend/.cache` | disk cache (diskcache) |
| `PILOT_REGION` | `19153,19169,19049,19015` | county FIPS with field polygons: Polk, Story, Dallas, Boone (IA) |
| `LOG_LEVEL` | `INFO` | every log line carries the request id |
| `STUB_DURATION_S` | `6` | analysis stub run time |
| `STUB_FAIL_RATE` | `0` | 0..1, share of analysis jobs that fail on purpose |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_S` | `30` / `60` | per-IP limit on `POST /analyses` and `POST /locations/resolve` |

After changing `PILOT_REGION`, run `make data-fields FORCE=1`.

## How it works

- **Layout:** `app/api` (one router per tag), `app/core` (config, errors, request id, cache, rate limit),
  `app/geo` (boundaries, point resolution, link parsing, tiles), `app/data_sources` (one client per
  upstream), `app/snapshots`, `app/analyses` (job store, engine protocol, stub).
- **Errors:** every error uses the `ErrorResponse` envelope with `ErrorCode`. Every response has
  `X-Request-Id` (the client's id is echoed if it is safe, otherwise a new one is generated).
- **Point resolution** (`POST /fields/resolve`, also used by locations, snapshots and analyses).
  Points outside the CONUS bbox or outside any US state return `OUTSIDE_COVERAGE`. A point inside a
  field polygon gives `field_polygon`. Otherwise the nearest polygon within `snap_radius_m` gives
  `snapped_point`. Otherwise a 500 m circle gives `buffered_point`. All distances, buffers and areas
  are computed in EPSG:5070.
- **Tiles:** prebuilt PMTiles archives (tippecanoe) served as XYZ
  `/v1/tiles/{fields|boundaries}/{z}/{x}/{y}.mvt`. Tiles are gzip-encoded. Empty tiles, tiles below
  `min_zoom` and tiles outside the pilot regions return 204.
- **Map links** (`POST /locations/resolve`): full Google/Apple URLs are parsed locally and never
  fetched. Only short-link hosts (`maps.app.goo.gl`, `goo.gl/maps`, `maps.apple`) are requested.
  Each hop must be https on the default port, with no userinfo, on an exact allow-listed host whose
  DNS answers are all public addresses. At most 3 hops in 5 s; only the `Location` header is read,
  never the body.
- **Snapshots:** all sources run concurrently with a 4 s per-source timeout (1.5 s soft timeout for
  USGS elevation, which often takes 6-13 s). A slow source keeps running in the background and fills
  a per-source cache, so the next request gets its value. A failed source yields
  `quality: unavailable` metrics; the request never fails because of it. Snapshots are cached 24 h by
  `field_id`, or by the point rounded to 0.01 degrees, but only when every source answered.
- **Analyses:** `POST /analyses` returns 202 and runs an asyncio background task. Jobs live in an
  in-memory store and are lost on restart. Identical requests within 10 min reuse the job.
  The ML model plugs in through `app/analyses/engine.py: AnalysisEngine`; set it in
  `app/services.py` in place of `StubAnalysisEngine`.

## Data sources

| Data | Source | Resolution | License / attribution | Known limits |
|---|---|---|---|---|
| Field polygons | USDA NASS Crop Sequence Boundaries 2024, GeoParquet mirror on Source Cooperative ([data](https://source.coop/ftw/harmonized-field-data/us_usda_cropland), [original](https://www.nass.usda.gov/Research_and_Science/Crop-Sequence-Boundaries/)) | polygons (algorithmic, built on the 30 m Cropland Data Layer) | mirror lists the license as "other", see [License and Liability](https://gee-community-catalog.org/projects/csb/#license-and-liability) | Not surveyed field boundaries. The mirror holds one year (2024) and one crop per polygon, so there is no crop history. Includes some non-crop classes (pasture, developed). |
| States, counties | US Census Bureau [TIGERweb REST](https://tigerweb.geo.census.gov/tigerwebmain/TIGERweb_restmapservice.html), current vintage | generalised to ~200 m for outlines | US Government work, public domain | Cartographic boundary zips block scripted downloads (HTTP 403), so the script uses TIGERweb instead |
| Humidity, temperature, precipitation, soil wetness | [NASA POWER](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) daily point API, community AG: `RH2M`, `T2M`, `PRECTOTCORR`, `GWETTOP`, `GWETROOT` | 0.5 x 0.625 deg (~55 km) | free; acknowledge "NASA Langley Research Center POWER Project" | Modeled (GEOS-IT / MERRA-2), not satellite-measured. Data lag about 1-2 days. Soil wetness is relative wetness (0-1), not volumetric moisture. |
| Organic matter, pH, texture | USDA NRCS SSURGO via [Soil Data Access](https://sdmdataaccess.sc.egov.usda.gov/WebServiceHelp.aspx) | survey polygons (1:12k-1:24k) | US Government work, public domain | Dominant component and surface horizon at the field anchor, not area-weighted. Survey representative values, not lab tests. |
| Elevation | USGS 3DEP via [Elevation Point Query Service](https://epqs.nationalmap.gov/v1/docs) | 1-10 m (reported per query) | US Government work, public domain | Slow (6-13 s), so the first snapshot often shows it as unavailable |
| Total nitrogen (estimated) | ISRIC [SoilGrids 2.0](https://rest.isric.org/soilgrids/v2.0/docs), `nitrogen` 0-5 cm mean | 250 m | CC BY 4.0 | Machine-learning estimate. Null in urban/water areas. The service is sometimes flaky. |

Not included yet: SMAP soil moisture (needs Earthdata login; contract keys `soil_moisture_*` are
reserved for it), slope, NLCD, annual precipitation normals.
