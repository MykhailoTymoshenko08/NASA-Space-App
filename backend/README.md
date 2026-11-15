# Field Shift backend

FastAPI backend for Field Shift, a NASA Space Apps crop-rotation decision-support tool for US farmers.
It implements `../contract/openapi.yaml` (v0.11.0). The contract is the source of truth; see
`../contract/CONTRACT_CHANGELOG.md` for changes.

## Setup

Requirements:

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 and all dependencies).
- Docker (for PostGIS, `docker-compose.yml`), or any PostgreSQL 16 + PostGIS 3 reachable via `DATABASE_URL`.
- [Git LFS](https://git-lfs.com) (`git lfs install` once): `data/csb_ia_il_ne.pmtiles` (540 MB) is stored
  in LFS, so a clone gets it without rebuilding.
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
git lfs pull              # data/csb_ia_il_ne.pmtiles, if the clone did not fetch it
make db                   # PostGIS on localhost:5433 (docker compose)
make ml                   # real ML service on localhost:8001 (model and demo data are committed)
make data-boundaries data-csb   # boundaries + CSB import into PostGIS (~15 min, 3.8 GB download once)
make dev                  # http://localhost:8000/v1/health, docs at /v1/docs
# or run the API in docker too: make up  (PostGIS + ML + API, the PMTiles mounted read-only)
```

| Command | What it does |
|---|---|
| `make install` | `uv sync` |
| `make dev` | API with auto-reload on `HOST:PORT` (default `127.0.0.1:8000`) |
| `make demo` | install, build data if missing, run the API without reload |
| `make db` | start PostGIS (`docker-compose.yml`, host port 5433) and wait until it is ready |
| `make ml` | build and start the real ML service on localhost:8001; works with `make dev` |
| `make test` | full test suite: no network, no `make data` needed (synthetic fixtures in a scratch PostGIS database; needs `make db`) |
| `make contract-check` | contract tests (real responses validated against the YAML) + `openapi.json` sync check |
| `make contract-json` | regenerate `../contract/openapi.json` from the YAML |
| `make up` | PostGIS + ML + API in docker compose; `data/csb_ia_il_ne.pmtiles` is a read-only volume |
| `make data` / `data-boundaries` / `data-csb` / `data-tiles` | build boundaries, import CSB into PostGIS, build `data/csb_ia_il_ne.pmtiles` (only needed after a data change; commit the new file, it is in LFS); add `FORCE=1` to rebuild (downloads stay cached) |
| `make lint` | ruff |
| `make docker` | build image `field-shift-backend` with the boundary data baked in |

Docker: `make up` (compose: PostGIS + ML + API), or `make docker` and then
`docker run --rm -p 8000:8000 -e FRONTEND_ORIGIN=<frontend url> -e DATABASE_URL=<postgis url> -v "$PWD/data/csb_ia_il_ne.pmtiles:/app/data/csb_ia_il_ne.pmtiles:ro" field-shift-backend`.
The image holds only the boundary data (~10 MB). Field polygons live in PostGIS and the field PMTiles
is mounted as a volume, so neither is in the image.

CI (`.github/workflows/backend.yml`) runs lint, `make contract-check` and `make test` with a PostGIS
service container.

## Getting the data (map, fields and tiles)

The map needs four inputs. Only the first comes with `git clone`; the others are downloaded or built
locally and are gitignored.

| What | Used for | How you get it | Size |
|---|---|---|---|
| `data/csb_ia_il_ne.pmtiles` | field polygons on the map, served at `/v1/tiles/fields.pmtiles` | Git LFS, step 1 | 540 MB |
| PostGIS tables `fields`, `field_crop_history`, `field_data_meta` | field clicks, `/fields/*`, crop history, coverage zooms | `make data-csb`, step 3 (downloads the CSB zip) | 3.2 GB database |
| `data/raw/csb/NationalCSB_2018-2025_rev23.zip` | source for the PostGIS import and for rebuilding the tiles | downloaded by `make data-csb`, or by hand (below) | 3.76 GB |
| `data/states.*`, `data/counties.*`, `data/boundaries.pmtiles` | state/county pickers, boundary tiles, county lookups | `make data-boundaries`, step 3 | about 10 MB |

The CDL crop-code list (`scripts/cdl_codes.json`) is in git, so nothing is needed for it.

### 1. Field tiles (Git LFS)

```sh
git lfs install                 # once per machine (Arch: pacman -S git-lfs, macOS: brew install git-lfs)
git lfs pull                    # fetches backend/data/csb_ia_il_ne.pmtiles
ls -l data/csb_ia_il_ne.pmtiles # must be 539948783 bytes
head -c 7 data/csb_ia_il_ne.pmtiles; echo   # must print "PMTiles"
sha256sum data/csb_ia_il_ne.pmtiles         # f8304f1a846347a2ac2a7709a6411322d1e423480af4e3732abe59a0833ae6f7
```

If the file is about 130 bytes and starts with `version https://git-lfs.github.com/spec/v1`, it is
still the LFS pointer: run `git lfs install && git lfs pull`. A GitHub "LFS bandwidth exceeded" error
means the repo's monthly LFS quota is used up. Then rebuild the tiles yourself (step 4) or get the file
from a teammate and copy it to `backend/data/`.

### 2. PostGIS

```sh
make db        # postgis/postgis:16-3.5 on localhost:5433, user/password/db fieldshift
```

### 3. Boundaries and the CSB import

```sh
make data-boundaries   # US Census TIGERweb states + counties (a few MB, ~1 min)
make data-csb          # downloads the CSB zip once (3.76 GB), imports IA, IL, NE into PostGIS (~12 min)
```

Check it worked:

```sh
psql postgresql://fieldshift:fieldshift@localhost:5433/fieldshift \
  -c "SELECT count(*) FROM fields"          # 1784509
```

`make data-csb` downloads the zip itself and resumes an interrupted download. The source is USDA NASS
Crop Sequence Boundaries 2018-2025, rev23, public domain:
- page: https://www.nass.usda.gov/Research_and_Science/Crop-Sequence-Boundaries/
- file: https://www.nass.usda.gov/sites/default/files/Research_and_Science/Crop-Sequence-Boundaries/datasets/NationalCSB_2018-2025_rev23.zip
- size: 3,758,023,527 bytes

To download it by hand (for example on a faster machine), note that the NASS server **answers only
HTTP Range requests**: a plain `curl -O` or a browser download gets `HTTP 500`. Fetch it in ranges:

```sh
cd backend
URL=https://www.nass.usda.gov/sites/default/files/Research_and_Science/Crop-Sequence-Boundaries/datasets/NationalCSB_2018-2025_rev23.zip
OUT=data/raw/csb/NationalCSB_2018-2025_rev23.zip
SIZE=3758023527
mkdir -p data/raw/csb && touch "$OUT"
while [ "$(wc -c < "$OUT")" -lt "$SIZE" ]; do
  HAVE=$(wc -c < "$OUT")
  curl -sS --fail -r "$HAVE-$((HAVE + 268435455))" "$URL" >> "$OUT" || sleep 5   # 256 MiB per request
done
unzip -l "$OUT" | head -5      # must list CSB1825.gdb/...; do NOT unzip, the import reads the zip directly
```

Re-run the loop if it stops: it continues from the current size. With the zip in place,
`make data-csb` skips the download. After the import you may delete the zip, but you need it again to
re-import or to rebuild the tiles.

### 4. Rebuilding the field tiles (only after a data change)

Needs [tippecanoe](https://github.com/felt/tippecanoe) 2.x and the PostGIS import from step 3.

```sh
make data-tiles FORCE=1        # PostGIS -> GeoJSONSeq -> tippecanoe -> data/csb_ia_il_ne.pmtiles (~7 min)
git add data/csb_ia_il_ne.pmtiles && git commit -m "Rebuild field PMTiles"   # stored via LFS
```

The build tries min zoom 11, then 12, then 13 (max zoom 14). It keeps the lowest zoom that fits
tippecanoe's tile size limit without dropping any field, and checks that every `field_id` is in the
tiles. It writes the chosen zooms to `field_data_meta` in PostGIS, so `/v1/meta/coverage` reports
them.

### 5. Check the whole chain

```sh
make dev
curl -s localhost:8000/v1/meta/coverage                       # field_tiles: z11-14, url .../v1/tiles/fields.pmtiles
curl -s -D - -o /dev/null -H "Range: bytes=0-16383" localhost:8000/v1/tiles/fields.pmtiles | head -1   # 206
curl -s -X POST localhost:8000/v1/fields/resolve -H 'content-type: application/json' \
  -d '{"point":{"lat":41.98,"lon":-93.70}}'                   # boundary_type estimated_csb, crop history
```

## Configuration (env vars)

| Variable | Default | Notes |
|---|---|---|
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS allowed origin |
| `DATA_DIR` | `backend/data` | prepared data (see `data/README.md`) |
| `CACHE_DIR` | `backend/.cache` | disk cache (diskcache) |
| `DATABASE_URL` | `postgresql://fieldshift:fieldshift@localhost:5433/fieldshift` | PostGIS with the CSB fields; empty or unreachable = every point is a buffered point (logged at startup) |
| `FIELDS_PMTILES_FILE` | `csb_ia_il_ne.pmtiles` | field PMTiles in `DATA_DIR`, served at `/v1/tiles/fields.pmtiles` |
| `FIELDS_PMTILES_URL` | empty | optional absolute URL of the same file on external hosting; empty = `coverage.field_tiles.url_template` is the backend's own `/v1/tiles/fields.pmtiles` |
| `LOG_LEVEL` | `INFO` | every log line carries the request id |
| `ANALYSIS_ENGINE` | `ml` | real HTTP ML engine; `stub` explicitly enables the old development demo |
| `ML_BASE_URL` | `http://127.0.0.1:8001` | ML origin for a local API; Compose sets `http://ml:8001` inside the API container |
| `ML_TIMEOUT_S` | `30` | timeout for an ML HTTP request; must be positive |
| `STUB_DURATION_S` | `6` | analysis stub run time |
| `STUB_FAIL_RATE` | `0` | 0..1, share of analysis jobs that fail on purpose |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_S` | `30` / `60` | per-IP limit on `POST /analyses`, `POST /locations/resolve`, `POST /auth/register` and `POST /auth/login` |
| `JWT_SECRET` | empty | signs access tokens, min 32 chars (`openssl rand -base64 48`). Empty: random per process, dev only |
| `ACCESS_TOKEN_TTL_MIN` | `15` | access token (JWT) lifetime |
| `REFRESH_TOKEN_TTL_DAYS` | `7` | refresh token (cookie) lifetime |
| `AUTH_COOKIE_SECURE` / `AUTH_COOKIE_SAMESITE` | `false` / `lax` | refresh cookie flags; see Auth below |

Tests use `TEST_DATABASE_ADMIN_URL` (default `postgresql://fieldshift:fieldshift@localhost:5433/postgres`)
to create and drop a scratch database.

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
  upstream), `app/field_info` (farmer context), `app/snapshots`, `app/analyses` (job store, engine protocol, stub).
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
  - Field polygons: one PMTiles file, `data/csb_ia_il_ne.pmtiles`, layer `fields` (`field_id`,
    `crop_class`, `area_ha`), served whole at `/v1/tiles/fields.pmtiles` with HTTP Range support (see
    "Serving the field tiles"). `/v1/meta/coverage` reports its absolute URL and zooms.
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
  USGS and SoilGrids requests allow 25 seconds per HTTP attempt and retry one transient transport
  failure or HTTP 502/503/504 after 250 ms. Background fetches stop after 60 seconds. Repeated
  requests share pending source work; shutdown cancels it before closing the HTTP client and cache.
  - SSURGO is area-weighted over the estimated field area: soil map units are clipped to the polygon
    in Soil Data Access. If that query fails it falls back to the anchor point, and the metric `note`
    says which was used.
  - The area query takes about 2-4 s, so a first snapshot of a field takes about 4 s; repeat
    requests are served from the cache.
- **Analyses:** `POST /analyses` returns 202 and runs an asyncio background task. After fetching the
  existing snapshot, `app/analyses/ml.py` calls `POST /ml/v1/analyze`. Jobs live in an in-memory store
  and are lost on restart. Identical requests within 10 min reuse the job; failed jobs can be retried.
  The backend strips `csb2025_` from a field ID, sends the anchor/geometry, county, area and mapped
  history, and translates crop names to ML slugs and CDL codes (including fallow and double crops).
  `options.crop_history` replaces mapped history when supplied. Selected priorities get weight 1.0,
  others 0.5; `low_input_cost` maps to ML's income index, like the previous stub. `horizon_years`
  reaches the real planner. Balanced requests use 0.5 for each of the five ML priorities.
  The adapter returns real scores, source-linked evidence and local-review notes in the existing
  frontend shape, sorted by score. Confidence bands are low below 0.5, medium below 0.8, high otherwise.
  Only the five scored criteria appear; pest-cycle and climate-risk scores are not invented.
  `result.ml_analysis` preserves the entire ML JSON, including crop suitability, month-by-month
  vulnerability, metrics, summary, deltas and numeric confidence. Climate normals are not inserted
  into historical `time_series`. The existing results UI continues to use adapted strategies.
  ML `partial` is a successful job with caveats. Constraints may leave fewer than three strategies;
  the adapter never manufactures alternatives. Income is an index, not a yield or dollar forecast.
  Each strategy also receives a rough dollar budget from the backend's existing crop calculator;
  this ML service predicts no yields. See "Rotation budgets" below.
  Coverage is IA/IL/NE/KS. Outside precomputed fields, crop history is required; missing history fails
  with `VALIDATION_ERROR`, unsupported states with `OUTSIDE_COVERAGE`. Service/network failures use
  `UPSTREAM_DATA_UNAVAILABLE`; temporary failures include `details.retry_after_s: 60`.
  Errors never switch to demonstration results. `ANALYSIS_ENGINE=stub` explicitly selects the old stub;
  `STUB_DURATION_S` and `STUB_FAIL_RATE` only apply there.

### Rotation budgets

`result.strategies[].budget` connects the actual ML crop sequence to the existing
`POST /profitability/estimate` calculation. ML's `scores.income` remains a separate relative index:
there is no calibrated conversion from that index, fit score or confidence to yield or dollars.
The frontend shows the budget on each strategy and optional local land/cover cost inputs during setup.

- For corn, soybeans and winter wheat in IA/IL/NE, use the historical low/base/high crop prices and
  published enterprise production costs. The default yield matches the selected cost profile: a
  high-productivity Illinois budget is never silently paired with a lower statewide yield, nor a
  dryland Nebraska budget with a mixed statewide yield. Reference yields are not field forecasts.
- Land cost is added once each year. Published corn-after-soybeans profiles replace the full cost and
  yield pair; their rotation effects receive no extra nitrogen discount. Year one uses actual
  mapped/farmer history, not the end of the proposed rotation. `cost_profile` identifies each budget.
- A terminated cover crop adds seed, planting and termination cost, with no grain revenue or automatic
  income for biological nitrogen, carbon, grazing or cost-share. There is no automatic all-in cover
  cost: supply local incremental seed, seeding and termination costs beyond the normal crop program.
  The former $99.85 program-schedule default has been removed. An observed
  [2025 direct-expense median](https://finpack.umn.edu/news/new-cover-crops-report-and-climate-smart-ag-resources-2/)
  is shown only as context; it is not a complete cost quote and is never inserted into calculations.
- `options.budget.land_rent_per_acre` replaces annual land cost; zero is valid. The equivalent
  `cover_cost_per_acre` replaces cost per cover planting. These assumptions never go to ML or alter ranking.
- `options.budget.crop_overrides` supplies gross revenue scenarios and all non-land production costs
  for a crop. It can fill missing sorghum/oats/barley/alfalfa/fallow budgets, or replace existing defaults.
  Crop keys are ML slugs. Farmer production totals receive no extra nitrogen discount. This advanced
  input is available through the API; the current setup UI exposes land and cover costs only. A
  combined slug such as `winter_wheat+soybean` supplies one full-year double-crop budget in growing order.
- Unknown crop costs, missing land costs or double crops produce `missing_inputs`; incomplete years
  have `scenarios: null`. No full-horizon total, annual average or current-rotation comparison is shown
  until every year is budgeted. Two full-yield single-crop budgets are not substituted for a double crop.
  Rotation cards omit the entire profitability block for incomplete budgets or budgets using placeholder
  inputs. Complete estimates remain visible even when their return is zero or negative. The API retains
  missing-input details for clients that need them.
- `annual_average` and `horizon_total` give USD/acre and estimated field profits. Field area is converted
  from hectares; field totals stay null when area is unknown. Deltas compare average annual profit
  under matching price scenarios and equal horizons. They are not confidence intervals.
- `return_before_land_per_acre` distinguishes the production return available to pay the land charge
  from net return after costs. Neither is cash flow: extension costs include labor, machinery ownership,
  depreciation and overhead. Per-year break-even prices divide modeled costs by reference yield.
- Every result is `is_illustrative: true`, with assumptions, sources and a separate `uses_placeholders`
  flag. Unverified rent and Iowa wheat defaults remain flagged. No inflation, discounting, future
  yield forecast or weather/soil suitability adjustment is applied to these dollar figures.

The [profitability audit](docs/profitability-audit.md) records verified sources, corrected assumptions,
and numerical comparisons. Negative economic returns remain possible and are not clipped to zero.

Example request using example farmer costs (not reference prices):

```json
{
  "selection": {"field_id": "csb2025_191825000314326"},
  "options": {
    "horizon_years": 3,
    "budget": {
      "land_rent_per_acre": 250,
      "cover_cost_per_acre": 45,
      "crop_overrides": [{
        "crop": "barley",
        "revenue_per_acre": {"low": 350, "base": 500, "high": 650},
        "production_cost_per_acre": 300
      }]
    }
  }
}
```

### Running ML without Docker

From the repository root, in a separate terminal:

```sh
cd ml
uv venv --python 3.12
uv pip install -r requirements-service.txt
ML_POWER_CACHE_DIR="$PWD/deploy/data/features/power_cache" \
  .venv/bin/uvicorn ml_service.main:app --host 127.0.0.1 --port 8001
```

Then run `make dev` in `backend/`. `curl http://127.0.0.1:8001/ml/health` must report `mode: real`.
The committed POWER cells cover the demo counties. New cells and soil queries need internet access;
the first request can return retry guidance while a climate cell downloads in the background.
The standalone ML Docker setup remains available in [`../ml/README_BACKEND.md`](../ml/README_BACKEND.md).

## Password change and recovery (Brevo SMTP)

The existing `/reset-password` frontend now calls the real API. All new passwords use the same rules
as registration: 8–128 characters, at least one letter and one digit.

| Endpoint | Request body | Success |
|---|---|---|
| `POST /v1/auth/change-password` | `{"current_password":"old-password1","new_password":"new-password2"}` plus bearer token | 204; sign in again |
| `POST /v1/auth/forgot-password` | `{"email":"farmer@example.com"}` | Empty 202 for both known and unknown accounts |
| `POST /v1/auth/reset-password` | `{"token":"token-from-email","new_password":"new-password2"}` | 204; sign in again |

Copy `.env.example` to `.env` if needed, then set `SMTP_USERNAME`, `SMTP_PASSWORD` and
`SMTP_FROM_EMAIL`. Never commit real credentials. In
[Brevo's SMTP settings](https://help.brevo.com/hc/en-us/articles/7924908994450-Send-transactional-emails-using-Brevo-SMTP),
use the displayed SMTP login, an **SMTP key**, and an authenticated sender address. The default relay
is `smtp-relay.brevo.com:587`, with mandatory STARTTLS and certificate validation. Port 465 uses
implicit TLS; 2525 uses STARTTLS. `SMTP_FROM_NAME` defaults to `Field Shift`.

Set `FRONTEND_ORIGIN` to the frontend origin that recipients can open (HTTPS in production). Reset
links use this configured origin, never the request's Host header. Restart the API after changing
configuration. Docker Compose passes these SMTP settings from `backend/.env` into the API container.
Without all three required values, forgot-password returns 502 for every email address. Local tests
replace SMTP with a capture or mock; they never send real emails.

Reset links expire in one hour, are stored only as SHA-256 hashes, and work once. A new request after
the one-minute per-account cooldown replaces the previous link. Password endpoints share a limit of
five requests per IP per minute. Delivery uses an in-process background task after the generic 202;
a process crash can lose pending mail. SMTP failures log only their exception class and remove the
failed link so the request can be retried. The accepted response does not promise inbox delivery.

A successful change or reset atomically updates the Argon2id hash, increments `users.auth_version`,
and deletes every refresh token and reset link for the account. Previously issued access JWTs fail
immediately. The client clears its local session and signs in again. No password-change settings
page is added; `entities/session.changePassword(currentPassword, newPassword)` exposes the API to UI
callers and clears the local session on success.

Schema expansion runs idempotently at startup: a default-zero `users.auth_version` column and a
`password_reset_tokens` table are added. Existing users, refresh tokens and saved fields are
preserved. JWTs issued before this release use version zero until a password update. Deploy by
restarting all API workers together: older workers do not enforce password-update revocation.
For a code rollback, leave the additive schema in place, rotate `JWT_SECRET`, and revoke refresh
tokens before running old workers; otherwise old code would accept sessions revoked by this release.
No schema removal is needed or performed.

## Field context after map selection

`POST /v1/fields/info` accepts the existing map-click payload, `{ "point": { "lat": 41.98,
"lon": -93.7 } }`. After resolving a field, pass `FieldSelection.anchor` as `point`.
There is no frontend in this repository; its contract already sends points, so this endpoint
does not add a polygon input. It does not resolve/snap the point again or call the ML pipeline.
It works without prepared boundaries or PostGIS. Only rough bounding boxes for Iowa, Illinois
and Nebraska are accepted; other points return 422 `OUTSIDE_COVERAGE`. Border false positives
are possible with these approximate envelopes.

All source calls run concurrently using async/httpx. The default response deadline is 4 seconds
per source (`SOURCE_TIMEOUT_S`). Slow work continues in the background for up to 60 seconds;
repeated requests for the same source and rounded point share that work. Non-terrain HTTP calls
have a 3.5-second timeout and a 1.5-second connect timeout. USGS terrain samples allow 25 seconds
per attempt and retry one transient transport failure or HTTP 502/503/504, bounded to 55 seconds
per sample. Failed, empty or incomplete data yields `value: null`, `quality: unavailable`
and a short `unavailable_reason`. Even an upstream outage returns 200 with all metric keys present.
Successful sources are cached in memory for 24 hours at coordinates rounded to four decimals
(about 11 m); the returned `point` is the actual rounded sample location. Incomplete sources are
retried on the next request, while other successful sources stay cached. `cached` is true only
when every source came from memory. Restarting the process clears this cache.

Sources, in priority order:

1. NASA POWER [monthly](https://power.larc.nasa.gov/docs/services/api/temporal/monthly/) and
   [climatology](https://power.larc.nasa.gov/docs/services/api/temporal/climatology/) point APIs:
   temperature, precipitation and solar radiation. Each recent value uses its latest complete
   12-month window, allowing up to six months of publication lag. Each value includes its own
   period; solar often lags meteorology. Means are day-weighted and rain rates become annual
   totals. The climatology baseline comes from NASA's response (2001–2025 during the live check),
   including leap-year weighting. Radiation units are checked and converted to MJ/m²/day.
   These are regional estimates, not measurements of the selected field.
2. NRCS [SSURGO / Soil Data Access](https://sdmdataaccess.sc.egov.usda.gov/WebServiceHelp.aspx):
   the dominant component at the point, its soil name, drainage, and shallowest horizon's
   texture, organic matter and pH. Missing attributes stay null independently. Reuses the
   existing SDA service; no local soil database or credentials needed.
3. USGS [3DEP EPQS](https://epqs.nationalmap.gov/v1/docs): point elevation plus a slope estimate
   from samples 100 m north, east, south and west. Slope is percent rise, not degrees or a field
   average. A failed neighbor does not discard the center elevation. Raw SRTM tiles are omitted
   to avoid Earthdata credentials and tile processing. EPQS can exceed the response deadline;
   successful background results populate the cache so later requests can recover terrain values.
4. USGS/MRLC [Annual NLCD](https://www.mrlc.gov/data-services-page), fixed 2024 land-cover product:
   a public WMS point query returns a readable class such as "Cultivated crops" at 30 m resolution.
   Pinning the year keeps demos reproducible without downloading rasters.

No SMAP, SoilGrids, or optional NASS QuickStats calls in this endpoint. They add latency or setup
without improving this first context card. Auth has not been merged: the explicit `TODO(auth)`
above the route in `app/api/fields.py` marks where to add `Depends(get_current_user)`.
Reusable fetch functions live in `app/field_info/sources.py`; orchestration and caching live in
`app/field_info/service.py`. Existing snapshots and analyses keep their current behavior.

```sh
curl -sS -X POST http://localhost:8000/v1/fields/info \
  -H 'Content-Type: application/json' \
  -d '{"point":{"lat":41.98,"lon":-93.7}}'
```

Example response excerpt from the live check (other metrics and metadata omitted):

```json
{
  "point": {"lat": 41.98, "lon": -93.7},
  "cached": false,
  "metrics": [
    {"key": "temperature_12m", "label": "Average temperature (latest 12 available months)", "value": 11.1, "unit": "degC", "period": {"start": "2025-10-01", "end": "2026-09-30"}},
    {"key": "precipitation_12m", "label": "Annual precipitation (latest 12 available months)", "value": 1042.2, "unit": "mm"},
    {"key": "dominant_soil", "label": "Dominant soil name", "value": "Webster", "unit": "none"},
    {"key": "soil_ph", "label": "Surface soil pH", "value": 6.5, "unit": "pH"},
    {"key": "elevation", "label": "Elevation above sea level", "value": null, "unit": "m", "unavailable_reason": "3DEP elevation did not return a value in time."},
    {"key": "land_cover", "label": "Land cover (2024)", "value": "Cultivated crops", "unit": "class"}
  ]
}
```

The full response includes `generated_at` and 14 fixed metric keys; every metric includes a
label, unit, source, resolution, quality and optional date/period/note for direct display.

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

Result (2026-11-14, one laptop, PostGIS in Docker):

| Item | Value |
|---|---|
| Polygons | 1,784,509 (IL 587,831, IA 628,672, NE 568,006); 0 dropped as empty; 190 became MultiPolygons after `ST_MakeValid` |
| Crop history | 14,276,072 rows (8 years for every polygon); every polygon has a 2025 crop |
| Import time | 730 s (staging ~2 min, geometry build ~7 min, history ~3.5 min) |
| PostGIS database | 3.2 GB |
| `csb_ia_il_ne.pmtiles` | 540 MB (539,948,783 bytes), z11-14, layer `fields`, every field present at z11 |
| Tile build time | 386 s (export + tippecanoe at the first try, min zoom 11) |

## Serving the field tiles

The frontend reads `data/csb_ia_il_ne.pmtiles` with the PMTiles client, which sends HTTP Range
requests. The backend serves the file at `GET`/`HEAD /v1/tiles/fields.pmtiles`:
- Starlette `FileResponse` answers a `Range` with 206 and `Content-Range`, and sets `ETag`.
- CORS allows `HEAD` and exposes `ETag`, `Content-Range` and `Content-Length`.
- `coverage.field_tiles.url_template` is the absolute URL of this route. It is built from the request,
  so with `--proxy-headers` it follows the public host behind a reverse proxy.

Sharing: the file is tracked with Git LFS (`.gitattributes`). After `make data-tiles FORCE=1`, commit
the new file so teammates get it with `git lfs pull`. GitHub's free LFS quota is 1 GB storage and
1 GB/month download, so each pull of the 540 MB file counts. Buy a data pack if the team pulls often.

Docker: `docker-compose.yml` mounts the file read-only into the `api` container
(`./data/csb_ia_il_ne.pmtiles:/app/data/csb_ia_il_ne.pmtiles:ro`); it is not copied into the image.

Check: `curl -s -D - -o /dev/null -H "Origin: http://localhost:5173" -H "Range: bytes=0-16383" http://localhost:8000/v1/tiles/fields.pmtiles`
must return `206`, `Content-Range` and `Access-Control-Allow-Origin`.

Every map pan sends a few Range requests through uvicorn. That is fine for the MVP. For heavy traffic,
put a CDN in front of the route, or upload the file to R2/S3 (Range + CORS) and set
`FIELDS_PMTILES_URL`. The frontend needs no change.

## Data sources

| Data | Source | Resolution | License / attribution | Known limits |
|---|---|---|---|---|
| Field polygons + crop history | USDA NASS [Crop Sequence Boundaries](https://www.nass.usda.gov/Research_and_Science/Crop-Sequence-Boundaries/) 2018-2025 (rev23), national FileGDB | polygons derived from the 30 m Cropland Data Layer | public domain (US Government work, per NASS); attribute "USDA NASS Crop Sequence Boundaries". (The Source Cooperative GeoParquet mirror lists its license as "other"; we use the NASS original.) | Algorithmic estimates of fields, not surveyed or ownership boundaries: real fields may be split or merged. Only IA, IL, NE are imported; elsewhere points become buffered points. Crop names from the [CDL codes](https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/metadata/metadata_CDL24_FGDC-STD-001-1998.xml). |
| States, counties | US Census Bureau [TIGERweb REST](https://tigerweb.geo.census.gov/tigerwebmain/TIGERweb_restmapservice.html), current vintage | generalised to ~200 m for outlines | US Government work, public domain | Cartographic boundary zips block scripted downloads (HTTP 403), so the script uses TIGERweb instead |
| Humidity, temperature, precipitation, soil wetness | [NASA POWER](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) daily point API, community AG: `RH2M`, `T2M`, `PRECTOTCORR`, `GWETTOP`, `GWETROOT` | 0.5 x 0.625 deg (~55 km) | free; acknowledge "NASA Langley Research Center POWER Project" | Modeled (GEOS-IT / MERRA-2), not satellite-measured. Data lag about 1-2 days. Soil wetness is relative wetness (0-1), not volumetric moisture. |
| Organic matter, pH, texture | USDA NRCS SSURGO via [Soil Data Access](https://sdmdataaccess.sc.egov.usda.gov/WebServiceHelp.aspx) | survey polygons (1:12k-1:24k) | US Government work, public domain | Area-weighted over the field area (dominant component of each map unit, surface horizon); point fallback noted in the metric. Survey representative values, not lab tests. |
| Elevation | USGS 3DEP via [Elevation Point Query Service](https://epqs.nationalmap.gov/v1/docs) | 1-10 m (reported per query) | US Government work, public domain | Slow (6-13 s), so the first snapshot often shows it as unavailable |
| Total nitrogen (estimated) | ISRIC [SoilGrids 2.0](https://rest.isric.org/soilgrids/v2.0/docs), `nitrogen` 0-5 cm mean | 250 m | CC BY 4.0 | Machine-learning estimate. Null in urban/water areas. The service is sometimes flaky. |

Not included in snapshots: SMAP soil moisture (needs Earthdata login; contract keys
`soil_moisture_*` are reserved for it), slope, NLCD, annual precipitation normals. The separate
field-context endpoint above includes slope, NLCD and annual climate context.
