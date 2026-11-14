# Fieldline frontend

Landing page and Field base-conditions page. "Fieldline" is a working name, set once in
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

### What the Field page calls

`/field?lat=..&lon=..` (or `?field_id=..`, which takes priority) → `POST /v1/snapshots`
with `{ selection: { point } }` or `{ selection: { field_id } }`. One call returns the resolved
field (`FieldSelection`) and its metrics. "Get analysis" → `POST /v1/analyses` → `/analysis/:jobId`.

### Mock scenarios (by requested point)

| Point | Result |
| --- | --- |
| Corn Belt, e.g. `41.5868, -93.625` | Mapped field, every metric answered |
| `lat >= 45`, e.g. `46.5, -96.8` | Soil moisture unavailable (card error state) |
| `lon > -90`, e.g. `40.1, -88.2` | No mapped field: 500 m circle |
| Outside the contiguous US | `422 OUTSIDE_COVERAGE` |
| `field_id=fld_missing` | `404 NOT_FOUND` |

## Structure (FSD)

```
src/
  app/        router, query client, root layout, mock worker start, global CSS
  pages/      landing, field, pick-field (stub), analysis (stub), sign-in (stub), not-found
  widgets/    site-header, site-footer, base-conditions
  features/   request-analysis (Get analysis button)
  entities/   field (URL state, snapshot query, sketch, labels), metric (cards, sources, formatting)
  shared/     api (client, errors, generated types), config, lib (units, geo), mocks, ui (kit, tokens)
```

Design tokens live only in `src/shared/ui/theme/tokens.css`. Components use `var(--…)`.

## Not built yet

- **Landing map.** Waits for the backend's map API (boundary and segment tiles). The stage is
  a placeholder that links to `/pick-field`.
- **Field boundary source.** Not chosen. Options to evaluate: USDA Crop Sequence Boundaries
  (the contract's example), Fields of The World, commercial field boundaries (for example
  Varda or Planet), and state parcel layers.
- **Pick-field, analysis results, sign-in.** Route stubs only.
