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
| Reset password | `/reset-password` | Stub (no contract route yet) |
| My fields, compare | `/my-fields` | `GET`/`POST /me/fields`, `DELETE /me/fields/{id}` (Save field button too). Compare: `POST /snapshots` per field |

Auth: the access token is kept in memory only; the refresh token is the backend's httpOnly cookie
(`credentials: "include"` on `/auth/*`). "Keep me signed in" off ends the session with the browser tab.

### Stubs (the design needs them, the contract does not have them)

Each sits behind one interface, so the real endpoint replaces one object:

- **Password reset** (`features/reset-password/api/password-reset-api.ts`, `PasswordResetApi`):
  request link, set new password. Works in mock mode; against a real backend it says reset is not available.
- **PDF export**: prints the result page (browser "Save as PDF"). No server endpoint.

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

## Structure (FSD)

```
src/
  app/        router (map pages load lazily), query client, root layout, mock worker, session restore
  pages/      landing, pick-field, field, analysis (setup + job), sign-in, sign-up, reset-password,
              my-fields, not-found
  widgets/    site-header, site-footer, explore-map, pick-map, analysis-result, saved-fields
  features/   sign-in, sign-up, sign-out, reset-password, pick-by-county, pick-by-location,
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
