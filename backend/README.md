# Field Shift backend

FastAPI backend for Field Shift, a NASA Space Apps crop-rotation decision-support tool for US farmers.
It implements `../contract/openapi.yaml` (v0.2.1). The contract is the source of truth; see
`../contract/CONTRACT_CHANGELOG.md` for changes.

## Setup

Requirements:

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 and all dependencies).
- [tippecanoe](https://github.com/felt/tippecanoe) 2.x, only needed to build vector tiles (`make data`).
  - Arch: `yay -S tippecanoe` (AUR)
  - macOS: `brew install tippecanoe`
  - Debian/Ubuntu: build from source (see the tippecanoe README).
- Internet access for `make data` (Iowa: ~90 MB of BLM pages, cached in `data/raw/`) and for live
  snapshot data.

From a fresh clone:

```sh
cd backend
cp .env.example .env      # optional, defaults work
make data                 # boundaries + PLSS sections/townships + tiles (idempotent)
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
| `make data` / `data-boundaries` / `data-plss` | build `data/`; add `FORCE=1` to rebuild existing outputs (downloads stay cached) |
| `make lint` | ruff |
| `make docker` | build image `field-shift-backend` with `data/` baked in (runs `make data` first if tiles are missing) |

Docker: `make docker`, then `docker run --rm -p 8000:8000 -e FRONTEND_ORIGIN=<frontend url> field-shift-backend`.
The image contains the prepared data (~75 MB for Iowa), so it needs no tippecanoe or data download at runtime.
Rebuild the image after `make data FORCE=1`.

CI (`.github/workflows/backend.yml`) runs lint, `make contract-check` and `make test`.

## Configuration (env vars)

| Variable | Default | Notes |
|---|---|---|
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS allowed origin |
| `DATA_DIR` | `backend/data` | prepared data (see `data/README.md`) |
| `CACHE_DIR` | `backend/.cache` | disk cache (diskcache) |
| `PLSS_STATES` | `IA` | state postal codes whose PLSS sections are prepared (must be PLSS states) |
| `LOG_LEVEL` | `INFO` | every log line carries the request id |
| `STUB_DURATION_S` | `6` | analysis stub run time |
| `STUB_FAIL_RATE` | `0` | 0..1, share of analysis jobs that fail on purpose |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_S` | `30` / `60` | per-IP limit on `POST /analyses`, `POST /locations/resolve`, `POST /auth/register` and `POST /auth/login` |
| `JWT_SECRET` | empty | signs access tokens, min 32 chars (`openssl rand -base64 48`). Empty: random per process, dev only |
| `ACCESS_TOKEN_TTL_MIN` | `15` | access token (JWT) lifetime |
| `REFRESH_TOKEN_TTL_DAYS` | `7` | refresh token (cookie) lifetime |
| `AUTH_COOKIE_SECURE` / `AUTH_COOKIE_SAMESITE` | `false` / `lax` | refresh cookie flags; see Auth below |

After changing `PLSS_STATES`, run `make data-plss FORCE=1`.

## Auth

Email + password accounts in the `DATABASE_URL` database (tables `users`, `refresh_tokens`, created on
startup if missing). Passwords are hashed with argon2id.

- `POST /v1/auth/register`, `POST /v1/auth/login` return `{access_token, expires_in, user}` and set the
  refresh token as an httpOnly cookie on path `/v1/auth`.
- Send the access token as `Authorization: Bearer <token>`. Protect a route with
  `user: User = Depends(get_current_user)` (`app/auth/deps.py`); it returns `401 UNAUTHORIZED` for a
  missing, invalid or expired token.
- `POST /v1/auth/refresh` (cookie only) returns a new access token and rotates the refresh token: each
  refresh token works once. `POST /v1/auth/logout` deletes it. `GET /v1/me` returns the current user.
- Refresh tokens are stored in the DB (sha256 only), not stateless JWTs, so logout and rotation really
  revoke them. Access tokens are stateless and stay valid until they expire (`ACCESS_TOKEN_TTL_MIN`).
- Frontend: call `/v1/auth/*` with `credentials: "include"`. Frontend and API on the same site (e.g.
  `localhost:5173` and `localhost:8000`): defaults work. On different sites (e.g. `app.vercel.app` and
  `api.fly.dev`): set `AUTH_COOKIE_SECURE=true` and `AUTH_COOKIE_SAMESITE=none` and serve over HTTPS.

## How it works

- **Layout:** `app/api` (one router per tag), `app/core` (config, errors, request id, cache, rate limit),
  `app/geo` (boundaries, point resolution, link parsing, tiles), `app/data_sources` (one client per
  upstream), `app/snapshots`, `app/analyses` (job store, engine protocol, stub).
- **Errors:** every error uses the `ErrorResponse` envelope with `ErrorCode`. Every response has
  `X-Request-Id` (the client's id is echoed if it is safe, otherwise a new one is generated).
- **Selectable unit = PLSS survey section** (contract 0.2). "Field" in API names means this unit: a
  BLM survey section of about 1 square mile, not a farm field. It carries no crop data, so
  `crop_class` is always null and `crop_history` is always empty.
- **Point resolution** (`POST /fields/resolve`, also used by locations, snapshots and analyses).
  - Outside the CONUS bbox or outside any US state: `OUTSIDE_COVERAGE`.
  - Inside a section: `field_polygon` with `boundary_type: plss_section`; the anchor is the clicked point.
  - Otherwise, nearest section within `snap_radius_m`: `snapped_point`, anchored at the section centroid.
  - Otherwise: a 500 m circle (`buffered_point`). This is what happens everywhere outside the prepared
    PLSS states.
  - `GET /fields/{id}` anchors at the section centroid.
  - All distances, buffers and areas are computed in EPSG:5070.
- **Tiles:** prebuilt PMTiles archives (tippecanoe) served as XYZ
  `/v1/tiles/{fields|boundaries}/{z}/{x}/{y}.mvt`, gzip-encoded.
  - `fields`: sections at z11-14; the client overzooms beyond 14.
  - Boundaries: `states`, `counties` (from z5) and `townships` (z8-10).
  - Empty tiles, tiles outside the zoom range and tiles outside the PLSS regions return 204.
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
  - SSURGO is area-weighted over the whole section: soil map units are clipped to the section polygon
    in Soil Data Access. If that query fails it falls back to the anchor point, and the metric `note`
    says which was used.
  - The area query takes about 2-4 s, so a first snapshot of a section takes about 4 s; repeat
    requests are served from the cache.
- **Analyses:** `POST /analyses` returns 202 and runs an asyncio background task. With no
  `options.crop_history`, the stub baseline is "Continue current practice (crops unknown)" and every
  strategy lists "No crop history provided". Jobs live in an
  in-memory store and are lost on restart. Identical requests within 10 min reuse the job.
  The ML model plugs in through `app/analyses/engine.py: AnalysisEngine`; set it in
  `app/services.py` in place of `StubAnalysisEngine`.

## PLSS data preparation

`scripts/prepare_plss.py`, run by `make data-plss`:

1. Pages through the BLM service (2,000 features per request, 0.5 s pause between requests) for each
   state in `PLSS_STATES`, caching raw pages in `data/raw/plss/`.
2. Keeps first divisions of type `SN` (Section) and `FS` (Fractional Section).
3. Drops the other first-division types:
   - protracted or unsurveyed blocks (`UP`, `PB`, `UN`);
   - quarter townships (`QT`), lots (`LT`), tracts (`TR`), meandered water (`MW`);
   - other or unknown types (`OT`, `UK`, `AR`, `UA`) and rows with no type.

   They are not survey sections a farmer would recognise; points there become buffered points.
4. Cleans and labels the sections:
   - `field_id` = `plss:` + `FRSTDIVID`, plus `-<FRSTDIVDUP>` when BLM marks a duplicate.
   - Rows that share an id are merged.
   - Multi-part shapes keep their largest polygon, because the contract requires a Polygon.
   - Labels ("Section 14, T79N R24W") are built from the `PLSSID`, because BLM's own township label
     text is inconsistent.
5. Assigns each section to a county by its interior point. `has_field_coverage` lists the counties
   that hold at least one section.
6. Writes `sections.parquet`, `townships.parquet` and `plss_meta.json`, builds `fields.pmtiles`, and
   rebuilds `boundaries.pmtiles` with the `townships` layer.

Iowa (2026-11-14):

| Item | Value |
|---|---|
| Sections | 56,703 (all type Section; 13 untyped rows dropped, 18 duplicate rows merged) |
| Townships | 1,512 |
| `fields.pmtiles` | 34.5 MB |
| `boundaries.pmtiles` | 7.0 MB |
| `sections.parquet` | 19 MB |
| Build time | about 40 s from cached pages, about 80 s with the download |

Whole PLSS area of the lower 48 (estimate): about 2.1M sections, about 1.3 GB `fields.pmtiles`,
about 1,050 BLM requests.

The CSB crop-field pipeline (`scripts/prepare_field_data.py`) is kept for reference but is not used.

## Data sources

| Data | Source | Resolution | License / attribution | Known limits |
|---|---|---|---|---|
| Selectable units (sections, townships) | BLM [National PLSS CadNSDI](https://gis.blm.gov/arcgis/rest/services/Cadastral/BLM_Natl_PLSS_CadNSDI/MapServer) MapServer: layer 2 "PLSS Section" (First Division), layer 1 "PLSS Township" | survey polygons (sections are about 1.6 x 1.6 km) | public domain (US Government work), provided "as is" with no warranty; attribute "Bureau of Land Management" | Survey grid cells, not farm fields or ownership. PLSS exists only in the 30 public-land states (not in the original 13 colonies, TX, KY, TN, WV, ME, VT, HI), so points elsewhere become buffered points. Only `PLSS_STATES` are prepared (default Iowa). |
| States, counties | US Census Bureau [TIGERweb REST](https://tigerweb.geo.census.gov/tigerwebmain/TIGERweb_restmapservice.html), current vintage | generalised to ~200 m for outlines | US Government work, public domain | Cartographic boundary zips block scripted downloads (HTTP 403), so the script uses TIGERweb instead |
| Humidity, temperature, precipitation, soil wetness | [NASA POWER](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) daily point API, community AG: `RH2M`, `T2M`, `PRECTOTCORR`, `GWETTOP`, `GWETROOT` | 0.5 x 0.625 deg (~55 km) | free; acknowledge "NASA Langley Research Center POWER Project" | Modeled (GEOS-IT / MERRA-2), not satellite-measured. Data lag about 1-2 days. Soil wetness is relative wetness (0-1), not volumetric moisture. |
| Organic matter, pH, texture | USDA NRCS SSURGO via [Soil Data Access](https://sdmdataaccess.sc.egov.usda.gov/WebServiceHelp.aspx) | survey polygons (1:12k-1:24k) | US Government work, public domain | Area-weighted over the section (dominant component of each map unit, surface horizon); point fallback noted in the metric. Survey representative values, not lab tests. |
| Elevation | USGS 3DEP via [Elevation Point Query Service](https://epqs.nationalmap.gov/v1/docs) | 1-10 m (reported per query) | US Government work, public domain | Slow (6-13 s), so the first snapshot often shows it as unavailable |
| Total nitrogen (estimated) | ISRIC [SoilGrids 2.0](https://rest.isric.org/soilgrids/v2.0/docs), `nitrogen` 0-5 cm mean | 250 m | CC BY 4.0 | Machine-learning estimate. Null in urban/water areas. The service is sometimes flaky. |

Not included yet: SMAP soil moisture (needs Earthdata login; contract keys `soil_moisture_*` are
reserved for it), slope, NLCD, annual precipitation normals.
