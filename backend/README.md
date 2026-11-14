# Field Shift backend

FastAPI backend for Field Shift, a NASA Space Apps crop-rotation decision-support tool for US farmers.
It implements `../contract/openapi.yaml` (v0.3.0). The contract is the source of truth; see
`../contract/CONTRACT_CHANGELOG.md` for changes.

## Setup

Requirements:

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 and all dependencies).
- Docker (for PostGIS, `docker-compose.yml`), or any PostgreSQL 16 + PostGIS 3 reachable via `DATABASE_URL`.
- [tippecanoe](https://github.com/felt/tippecanoe) 2.x, only needed to build vector tiles (`make data`).
  - Arch: `yay -S tippecanoe` (AUR)
  - macOS: `brew install tippecanoe`
  - Debian/Ubuntu: build from source (see the tippecanoe README).
- Internet access for `make data` (the CSB download is 3.76 GB, cached in `data/raw/csb/`; boundaries
  are a few MB) and for live snapshot data.
- Disk: about 10 GB free for the CSB zip, the PostGIS volume and the PMTiles build.

From a fresh clone:

```sh
cd backend
cp .env.example .env      # optional, defaults work
make db                   # PostGIS on localhost:5433 (docker compose)
make data                 # boundaries + CSB import into PostGIS + field PMTiles (idempotent)
make serve-tiles          # field PMTiles on http://localhost:8787 (Range + CORS), separate terminal
make dev                  # http://localhost:8000/v1/health, docs at /v1/docs
```

| Command | What it does |
|---|---|
| `make install` | `uv sync` |
| `make dev` | API with auto-reload on `HOST:PORT` (default `127.0.0.1:8000`) |
| `make demo` | install, build data if missing, run the API without reload |
| `make db` | start PostGIS (`docker-compose.yml`, host port 5433) and wait until it is ready |
| `make test` | full test suite: no network, no `make data` needed (synthetic fixtures in a scratch PostGIS database; needs `make db`) |
| `make contract-check` | contract tests (real responses validated against the YAML) + `openapi.json` sync check |
| `make contract-json` | regenerate `../contract/openapi.json` from the YAML |
| `make data` / `data-boundaries` / `data-csb` / `data-tiles` | build boundaries, import CSB into PostGIS, build `data/csb_ia_il_ne.pmtiles`; add `FORCE=1` to rebuild (downloads stay cached) |
| `make serve-tiles` | local static server for the field PMTiles (Range + CORS for `FRONTEND_ORIGIN`) |
| `make lint` | ruff |
| `make docker` | build image `field-shift-backend` with the boundary data baked in |

Docker: `make docker`, then
`docker run --rm -p 8000:8000 -e FRONTEND_ORIGIN=<frontend url> -e DATABASE_URL=<postgis url> -e FIELDS_PMTILES_URL=<https url> field-shift-backend`.
The image holds only the boundary data (~10 MB). Field polygons live in PostGIS and the field tiles on
static hosting, so neither is in the image.

CI (`.github/workflows/backend.yml`) runs lint, `make contract-check` and `make test` with a PostGIS
service container.

## Configuration (env vars)

| Variable | Default | Notes |
|---|---|---|
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS allowed origin |
| `DATA_DIR` | `backend/data` | prepared data (see `data/README.md`) |
| `CACHE_DIR` | `backend/.cache` | disk cache (diskcache) |
| `DATABASE_URL` | `postgresql://fieldshift:fieldshift@localhost:5433/fieldshift` | PostGIS with the CSB fields; empty or unreachable = every point is a buffered point (logged at startup) |
| `FIELDS_PMTILES_URL` | `http://localhost:8787/csb_ia_il_ne.pmtiles` | public URL of the field PMTiles, sent as `coverage.field_tiles.url_template` |
| `LOG_LEVEL` | `INFO` | every log line carries the request id |
| `STUB_DURATION_S` | `6` | analysis stub run time |
| `STUB_FAIL_RATE` | `0` | 0..1, share of analysis jobs that fail on purpose |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_S` | `30` / `60` | per-IP limit on `POST /analyses` and `POST /locations/resolve` |

Tests use `TEST_DATABASE_ADMIN_URL` (default `postgresql://fieldshift:fieldshift@localhost:5433/postgres`)
to create and drop a scratch database.

## How it works

- **Layout:** `app/api` (one router per tag), `app/core` (config, errors, request id, cache, rate limit),
  `app/geo` (boundaries, point resolution, link parsing, tiles), `app/data_sources` (one client per
  upstream), `app/snapshots`, `app/analyses` (job store, engine protocol, stub).
- **Errors:** every error uses the `ErrorResponse` envelope with `ErrorCode`. Every response has
  `X-Request-Id` (the client's id is echoed if it is safe, otherwise a new one is generated).
- **Selectable unit = estimated CSB field area** (contract 0.3). USDA Crop Sequence Boundaries
  polygons for Iowa, Illinois and Nebraska only. They are algorithmic estimates from satellite crop
  maps, not surveyed or ownership boundaries: a real field may be split or merged. Each carries the
  latest crop (`crop_class`) and up to 8 years of `crop_history`.
- **Supported states:** fixed in `app/core/config.py: FIELD_STATES` (IA, IL, NE). `/geo/states` lists
  only these, `/geo/states/{fips}/counties` returns 404 for others. County lookups for buffered points
  work in all of CONUS.
- **Point resolution** (`POST /fields/resolve`, also used by locations, snapshots and analyses), all
  in PostGIS (`app/geo/field_store.py`).
  - Outside the CONUS bbox or outside any US state: `OUTSIDE_COVERAGE`.
  - Inside a polygon (`ST_Contains`, GiST index; smallest wins on overlap): `field_polygon` with
    `boundary_type: estimated_csb`; the anchor is the clicked point.
  - Otherwise, nearest polygon within `snap_radius_m`: 8 KNN candidates (`geom <-> point`) ranked by
    true EPSG:5070 distance. `snapped_point`, anchored at the polygon centroid.
  - Otherwise: a 500 m circle (`buffered_point`). This is what happens everywhere outside IA, IL, NE.
  - `GET /fields/{id}` anchors at the polygon centroid.
  - Distances, buffers and areas are computed in EPSG:5070. The rare MultiPolygon (from
    `ST_MakeValid`) is returned as its part containing the point, else its largest part.
- **Tiles:**
  - Field polygons: one static PMTiles file, `data/csb_ia_il_ne.pmtiles`, layer `fields` (`field_id`,
    `crop_class`, `area_ha`), hosted outside the backend (see "Hosting the field tiles"). The backend
    only reports its URL and zooms in `/v1/meta/coverage`.
  - Boundaries: `/v1/tiles/boundaries/{z}/{x}/{y}.mvt` (`states`, `counties` from z5), gzip-encoded,
    204 for empty tiles.
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
  - SSURGO is area-weighted over the estimated field area: soil map units are clipped to the polygon
    in Soil Data Access. If that query fails it falls back to the anchor point, and the metric `note`
    says which was used.
  - The area query takes about 2-4 s, so a first snapshot of a field takes about 4 s; repeat
    requests are served from the cache.
- **Analyses:** `POST /analyses` returns 202 and runs an asyncio background task. The stub baseline
  ("Continue current rotation: ...") comes from `options.crop_history` when the farmer sent a
  correction, else from the CSB `crop_history` of the selection. With neither (buffered points), it is
  "Continue current practice (crops unknown)" and every strategy lists "No crop history provided". Jobs live in an
  in-memory store and are lost on restart. Identical requests within 10 min reuse the job.
  The ML model plugs in through `app/analyses/engine.py: AnalysisEngine`; set it in
  `app/services.py` in place of `StubAnalysisEngine`.

## CSB data preparation

`scripts/prepare_csb.py`, run by `make data-csb` (import) and `make data-tiles` (tiles):

1. Downloads `NationalCSB_2018-2025_rev23.zip` (3.76 GB) from NASS once into `data/raw/csb/`. The NASS
   server answers only HTTP Range requests (a plain GET returns 500), so the download is ranged and
   resumable.
2. Streams the FileGDB layer `national1825` with pyogrio (`/vsizip/`, no unzip), filtered to
   `STATEFIPS IN ('17','19','31')`, into an UNLOGGED staging table.
3. Builds `fields_new` and `field_crop_history_new`:
   - `ST_MakeValid`, polygons only, empties dropped;
   - `area_ha` in EPSG:5070 (the source CRS has the EPSG:5070 parameters), geometry stored in EPSG:4326;
   - `field_id = csb2025_<CSBID>` (CSBID is unique only within one edition);
   - CDL codes mapped to names with `scripts/cdl_codes.json` (official CDL categorization codes);
     codes 0 and 81 (background, clouds) are left out of the history.
4. Builds the GiST index, then swaps the new tables in within one transaction. Re-running skips when
   the same CSB release is already imported; `FORCE=1` re-imports.
5. Tiles: exports from PostGIS to GeoJSONSeq and runs tippecanoe with no dropping
   (`-r1 --no-tiny-polygon-reduction --no-feature-limit`, default 500 KB tile limit). It tries min zoom
   11, 12, 13 (max 14) and keeps the lowest that builds, then decodes the min-zoom tiles and checks that
   every `field_id` is present. Zooms and stats go to `field_data_meta.tiles`, which `/meta/coverage`
   reads.

Result (2026-11-14): CSB_RESULTS_TABLE

## Hosting the field tiles

PMTiles clients read the file with HTTP Range requests. The host must support `Range` and CORS.
Static page hosts without Range support (GitHub Pages, most "static site" hosts) do not work.

Development: `make serve-tiles` serves `data/*.pmtiles` on `http://localhost:8787` with Range, ETag
and CORS for `FRONTEND_ORIGIN` only (add more with `--origin`). Keep `FIELDS_PMTILES_URL` at its
default.

Production (Cloudflare R2; any S3-compatible store works the same way):

1. Create a bucket, e.g. `field-shift-tiles`, and give it a public custom domain (R2 > bucket >
   Settings > Custom Domains) or the `r2.dev` URL.
2. Upload (multipart is required for files over 5 GB, and both tools do it):
   - `rclone copyto data/csb_ia_il_ne.pmtiles r2:field-shift-tiles/csb_ia_il_ne.pmtiles`, or
   - `aws s3 cp data/csb_ia_il_ne.pmtiles s3://field-shift-tiles/ --endpoint-url https://<account>.r2.cloudflarestorage.com`
3. CORS policy on the bucket (only the frontend origins; GET and HEAD; header `Range`; expose `ETag`):

   ```json
   [{
     "AllowedOrigins": ["https://<frontend origin>", "http://localhost:5173"],
     "AllowedMethods": ["GET", "HEAD"],
     "AllowedHeaders": ["Range"],
     "ExposeHeaders": ["ETag"],
     "MaxAgeSeconds": 86400
   }]
   ```

   Apply with the R2 dashboard (Settings > CORS policy) or
   `aws s3api put-bucket-cors --bucket field-shift-tiles --cors-configuration file://cors.json --endpoint-url ...`
   (wrap the list as `{"CORSRules": [...]}` for the S3 API).
4. Set `FIELDS_PMTILES_URL=https://<domain>/csb_ia_il_ne.pmtiles` on the backend.
5. Check from the frontend origin:
   `curl -sI -H "Origin: https://<frontend origin>" -H "Range: bytes=0-16383" $FIELDS_PMTILES_URL`
   must return `206`, `Content-Range`, `Access-Control-Allow-Origin` and `Access-Control-Expose-Headers: ETag`.

Upload a rebuilt file under a new name (or purge the CDN cache): PMTiles clients cache the header by
ETag.

## Data sources

| Data | Source | Resolution | License / attribution | Known limits |
|---|---|---|---|---|
| Field polygons + crop history | USDA NASS [Crop Sequence Boundaries](https://www.nass.usda.gov/Research_and_Science/Crop-Sequence-Boundaries/) 2018-2025 (rev23), national FileGDB | polygons derived from the 30 m Cropland Data Layer | public domain (US Government work, per NASS); attribute "USDA NASS Crop Sequence Boundaries". (The Source Cooperative GeoParquet mirror lists its license as "other"; we use the NASS original.) | Algorithmic estimates of fields, not surveyed or ownership boundaries: real fields may be split or merged. Only IA, IL, NE are imported; elsewhere points become buffered points. Crop names from the [CDL codes](https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/metadata/metadata_CDL24_FGDC-STD-001-1998.xml). |
| States, counties | US Census Bureau [TIGERweb REST](https://tigerweb.geo.census.gov/tigerwebmain/TIGERweb_restmapservice.html), current vintage | generalised to ~200 m for outlines | US Government work, public domain | Cartographic boundary zips block scripted downloads (HTTP 403), so the script uses TIGERweb instead |
| Humidity, temperature, precipitation, soil wetness | [NASA POWER](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) daily point API, community AG: `RH2M`, `T2M`, `PRECTOTCORR`, `GWETTOP`, `GWETROOT` | 0.5 x 0.625 deg (~55 km) | free; acknowledge "NASA Langley Research Center POWER Project" | Modeled (GEOS-IT / MERRA-2), not satellite-measured. Data lag about 1-2 days. Soil wetness is relative wetness (0-1), not volumetric moisture. |
| Organic matter, pH, texture | USDA NRCS SSURGO via [Soil Data Access](https://sdmdataaccess.sc.egov.usda.gov/WebServiceHelp.aspx) | survey polygons (1:12k-1:24k) | US Government work, public domain | Area-weighted over the field area (dominant component of each map unit, surface horizon); point fallback noted in the metric. Survey representative values, not lab tests. |
| Elevation | USGS 3DEP via [Elevation Point Query Service](https://epqs.nationalmap.gov/v1/docs) | 1-10 m (reported per query) | US Government work, public domain | Slow (6-13 s), so the first snapshot often shows it as unavailable |
| Total nitrogen (estimated) | ISRIC [SoilGrids 2.0](https://rest.isric.org/soilgrids/v2.0/docs), `nitrogen` 0-5 cm mean | 250 m | CC BY 4.0 | Machine-learning estimate. Null in urban/water areas. The service is sometimes flaky. |

Not included yet: SMAP soil moisture (needs Earthdata login; contract keys `soil_moisture_*` are
reserved for it), slope, NLCD, annual precipitation normals.
