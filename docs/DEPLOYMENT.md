# Deployed backend: how the frontend connects

The backend API (with its database and ML service) is deployed and reachable at the URL below. The frontend is
hosted separately on Vercel (see [Frontend hosting](#frontend-hosting)).

## Endpoints

| What | Value |
|---|---|
| API base URL | `https://fieldshift-api-66d5a9555f84.herokuapp.com/v1` |
| Health check | `GET /v1/health` → `{"status":"ok"}` |
| API contract | [`contract/openapi.yaml`](../contract/openapi.yaml) (same as local dev) |
| Field PMTiles | Absolute URL in `GET /v1/meta/coverage` → `field_tiles.url_template` (served by the API, HTTP range requests) |
| Boundary / PLSS tiles | `/v1/tiles/boundaries/{z}/{x}/{y}.mvt`, `/v1/tiles/plss/{z}/{x}/{y}.mvt` |

The ML service is internal: the browser never calls it.

## Connecting the frontend

Two options. **A is recommended.**

**A. Proxy `/v1` through the frontend host (same origin).** Configure a rewrite on the frontend host so
`https://<frontend>/v1/*` is forwarded to `https://fieldshift-api-66d5a9555f84.herokuapp.com/v1/*`, and build with:

```
VITE_API_BASE_URL=/v1
VITE_USE_MOCKS=0
```

A relative base URL is turned into an absolute one from the page origin (`src/shared/config/env.ts`), because
MapLibre does not resolve relative tile URLs. With a proxy the refresh-token cookie is first-party, so sign-in
survives page reloads in every browser. Examples: Vercel `rewrites` in `vercel.json`, Netlify
`/v1/* https://fieldshift-api-66d5a9555f84.herokuapp.com/v1/:splat 200` in `_redirects`.

**B. Call the API directly (cross-origin).** Build with
`VITE_API_BASE_URL=https://fieldshift-api-66d5a9555f84.herokuapp.com/v1`. Works for every public call, but the
refresh-token cookie is then a third-party cookie (`SameSite=None; Secure`), which Safari and Firefox (strict
mode) block: users would be signed out on every reload.

Either way the field PMTiles file is loaded directly from the API URL, so your frontend origin must be one of
the backend's allowed origins (see [Frontend hosting](#frontend-hosting)).

## Running the local frontend against the deployed backend

```
cd frontend
cat > .env.remote <<'EOF'
VITE_API_BASE_URL=/v1
VITE_USE_MOCKS=0
VITE_API_PROXY_TARGET=https://fieldshift-api-66d5a9555f84.herokuapp.com
EOF
npm run dev:remote        # http://localhost:5173, /v1 proxied by the Vite dev server
```

`.env.*` files are gitignored, so each developer creates `.env.remote` once. Field tiles work
because the backend also allows `http://localhost:5173`.

## Behaviour to expect

- **Cold starts.** The ML service sleeps after 30 min without traffic: the first analysis after that waits
  ~10–30 s longer. The database suspends after 5 min idle: the first request touching it adds ~1 s. Keep
  loading states and polling tolerant of this.
- **Analysis jobs are in memory.** A backend restart (deploy, config change, daily restart) drops
  running and finished jobs: polling an old `job_id` then returns 404, start a new analysis.
- **Rate limits** per client IP, each group separately: analyses, location resolve, auth, comparisons and
  profitability 30 requests per 60 s; password endpoints 5 per 60 s → `429` with `Retry-After`.
- **Password reset email is off** for now: `POST /v1/auth/forgot-password` answers `502`
  `UPSTREAM_DATA_UNAVAILABLE` ("Password reset email is unavailable"). Show that message; we will tell you
  when email is enabled.

## Frontend hosting

| Item | Value |
|---|---|
| Production frontend origin | `https://selo-ai-seven.vercel.app` |
| How it connects | Option A: Vercel proxies `/v1` to the API |
| Other allowed origins | `http://localhost:5173` (`npm run dev:remote`) |

The backend allows exactly these browser origins (CORS, needed for the field tiles). For another origin, such as
a Vercel preview URL that must load field tiles, ask us to add it.
