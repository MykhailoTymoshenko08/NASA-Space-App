# Fieldline frontend

Landing map, pick a field, base conditions, analysis, accounts and saved fields. "Fieldline" is a working name, set once in
`src/shared/config/brand.ts`.

Stack: Vite, React 19, TypeScript (strict), React Router 7, TanStack Query, openapi-fetch.
Architecture: [Feature-Sliced Design](https://feature-sliced.design), checked by Steiger.

## Run

```bash
npm install
cp .env.example .env.local   # VITE_USE_MOCKS=1 runs without a backend
npm run dev                  # http://localhost:5173
```

In mock mode, open a sample field at `/field?lat=41.5868&lon=-93.625`. There is also a link
on `/pick-field`. A blue banner marks every mock-mode page.

| Script | What it does |
| --- | --- |
| `npm run dev` | Dev server |
| `npm run build` | Type-check and production build |
| `npm test` | Unit and page tests (Vitest, jsdom, MSW node server) |
| `npm run lint:fsd` | Feature-Sliced Design rules (Steiger) |
| `npm run gen:api` | Regenerate `src/shared/api/schema.gen.ts` from `../contract/openapi.yaml` |

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000/v1` | Our backend. The browser calls nothing else. |
| `VITE_USE_MOCKS` | unset | `1` answers API calls in the browser with MSW (`src/shared/mocks`). |
| `VITE_API_PROXY_TARGET` | unset | Dev server only: forward `/v1` to this backend (`npm run dev:remote` with `.env.remote`, see [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md)). |

No API keys belong in the client.

## API contract

`../contract/openapi.yaml` is the source of truth. Never hand-write API types:
change the contract first (and add an entry to `CONTRACT_CHANGELOG.md`), then run
`npm run gen:api` and fix the compile errors.

`gen:api` runs `openapi-typescript` through `npx` with TypeScript 5, because
`openapi-typescript` does not support the TypeScript 7 this project uses.

### What each screen calls

| Screen | Route | API |
| --- | --- | --- |
| Landing map | `/` | `GET /meta/coverage`, `GET /geo/states`, `GET /geo/counties/{fips}`, boundary tiles `GET /tiles/boundaries/{z}/{x}/{y}.mvt`, field polygons from the PMTiles file at `coverage.field_tiles.url_template`, `GET /fields/{field_id}` on a field click |
| Pick a field | `/pick-field` | `GET /geo/states`, `GET /geo/states/{fips}/counties`, `POST /locations/resolve` (link or coordinates box), `GET /fields/{id}` or `POST /fields/resolve` (map click) |
| Base conditions | `/field?field_id=..` or `?lat=..&lon=..` | `POST /snapshots` |
| Analysis setup | `/analysis?field_id=..` | `POST /snapshots` (cached), `POST /analyses` (202) |
| Analysis | `/analysis/:jobId?field_id=..&p=..&h=..` | `GET /analyses/{job_id}`, every 2 s, every 5 s after 30 s |
| Sign in, create account | `/sign-in`, `/sign-up` | `POST /auth/login`, `POST /auth/register`, `POST /auth/refresh` (on start), `POST /auth/logout` |
| Reset password | `/reset-password` | `POST /auth/forgot-password`, `POST /auth/reset-password` |
| Change password | `/account/password` | `POST /auth/change-password` (account menu link) |
| My fields, compare | `/my-fields` | `GET`/`POST /me/fields`, `DELETE /me/fields/{id}` (Save field button too). Compare: `POST /snapshots` per field |
| Compare and rank (to build) | — | `POST /comparisons/saved-fields`, `POST /comparisons/area`: see [docs/field-comparison.md](docs/field-comparison.md) |

Auth: the access token is kept in memory only; the refresh token is the backend's httpOnly cookie
(`credentials: "include"` on `/auth/*`). "Keep me signed in" off ends the session with the browser tab.

Password recovery sends email through the backend's Brevo SMTP configuration (see `backend/README.md`).
The email link opens `/reset-password?token=...`; the page captures the token in memory, removes it
from the URL, and sends it only in the reset request body. Links expire after one hour and work once.
The page uses a generic confirmation for known and unknown accounts. A successful reset clears the
local session; the user signs in again. Referrers are disabled to keep reset links out of external requests.

Signed-in users change their password at `/account/password` (account menu, "Change password").
The form calls `entities/session.changePassword(currentPassword, newPassword)`, which calls
`POST /auth/change-password` and clears the local session on success; the page then asks the user
to sign in again. A 401 with `details.reason: invalid_credentials` marks the current password as
wrong; any other 401 means the session ended, so the session is cleared and the user signs in again.

### PDF export

Prints the result page (browser "Save as PDF"). No server endpoint.

### Mock scenarios

| Input | Result |
| --- | --- |
| A point in Iowa, Illinois or Nebraska, e.g. `41.5868, -93.625` | Estimated field area (snapped), every metric answered |
| Elsewhere in the contiguous US, e.g. `39.7392, -104.9903` | 300 m buffered circle, no field id |
| `lat >= 45`, e.g. `46.5, -96.8` | Soil moisture "Not available"; analyses fail (`UPSTREAM_DATA_UNAVAILABLE`) |
| Outside the contiguous US | `422 OUTSIDE_COVERAGE` |
| `my back forty` in the link box | `422 UNPARSEABLE_INPUT` |

Mock mode serves no map tiles, so the maps show no outlines; everything else works.
Demo accounts and saved fields are kept in `localStorage`. Saving outside Iowa, Illinois or Nebraska
returns `422 OUTSIDE_COVERAGE`, as the real API does.
In mock mode, password recovery uses the explicit "Demo: open the link from the email" button
instead of sending mail. Reset an existing demo account; the new password replaces its old password.

## Structure (FSD)

```
src/
  app/        router (map pages load lazily), query client, root layout, mock worker, session restore
  pages/      landing, pick-field, field, analysis (setup + job), sign-in, sign-up, reset-password,
              change-password, my-fields, not-found
  widgets/    site-header, explore-map, pick-map, analysis-result, saved-fields
  features/   sign-in, sign-up, sign-out, reset-password, change-password, pick-by-county, pick-by-location,
              save-field, configure-analysis, export-pdf
  entities/   session, field, metric, region, analysis, saved-field
  shared/     api (client, auth token, errors, generated types), config, lib (units, geo, dates),
              mocks, ui (kit, form, choice, progress, map, map-overlay, tokens)
```

Design tokens live only in `src/shared/ui/theme/tokens.css`. Components use `var(--…)`.
The design handoff (`design/`) is local only and ignored by git.

## Open questions

- Segments (the 5 by 5 grid between county and field in the design) are not in the API. The map goes
  from county straight to field outlines at `field_tiles.min_zoom`; clicking in county view zooms there.
- Registration has no name field in the contract, so Create account asks for email and password only.
- Saved fields get a default name ("Polk, IA"); renaming (`PATCH /me/fields/{id}`), `refresh-info` and
  `POST /profitability/estimate` (contract 0.5.0) are not in the design yet, so the UI does not use them.
