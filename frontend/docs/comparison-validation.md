# Comparison validation

Validated locally on 2026-11-15 with Chromium, a disposable PostGIS database, two synthetic CSB fields,
saved point fields, and live upstream data services. Production deployment was not part of this check.

## Findings and changes

The saved-field screen previously called `/snapshots` separately for each field. It never reached the
comparison API, so users could not see rents, budgets, soil winners, history or cautions.

The screen now uses `/comparisons/saved-fields`. It supports two to four fields, asking rents including
zero, a shared crop rotation and a one-to-five-year horizon. The server determines winners and budgets.
Updates require the Update comparison button. Previous results remain visible during loading and after
an update failure, with an explicit message. Rate-limit cooldowns respect `Retry-After` and recover after
a successful request. Reconnect does not bypass the cooldown.

Summary cards show returns, break-even rent, strengths, cautions and budget details. Grouped rows show
money, land, soil, history and climate. Phone rows stack field pairs with their labels, so users can read
all values without horizontal scrolling. Available data notes collapse; missing-data reasons stay visible.
Money retains negative signs and loss labels. Metric values convert to US display units. Unknown values
remain unavailable. Mock mode labels sample land data and withholds financial estimates.

## Verification

- Backend comparison, saved-field and financial suites: 68 tests passed.
- Backend contract checks: 211 tests passed; generated OpenAPI JSON synchronized. Focused Ruff checks passed.
- Frontend: 161 tests passed on the comparison-only branch based on updated `origin/main`;
  production build, TypeScript and FSD lint passed. The earlier shared integration tree passed 164 tests.
- Browser suite: all 10 checks passed, with no uncaught page errors.
- Independent mock-mode browser smoke: registration, two saves, comparison and zero rent passed.
- Screenshots inspected for desktop and phone, with two and four fields. Layout bounds passed at
  320, 390, 760, 1024 and 1440 px, including expanded budget details.

The browser suite covers sign-in protection; registration; coordinate resolution; saving; selecting;
comparing; changing rents and reversing winners; zero and invalid rents; 503 recovery with retained
results; 429 cooldown and reconnect; shared crop plans; unavailable wheat budgets; phone navigation;
point limitations; the four-field cap; and responsive layout bounds.

Live HTTP checks also cover area ranking: initial soil filling, completion, pagination, crop filters,
pinned fields, duplicate-ID rejection and unauthenticated rejection. A cold comparison took about four
seconds. Changing rent changed returns by exactly the corresponding amount and reversed the best field.

## Reproduce browser checks

Start the disposable backend from `backend/`:

```bash
AUTH_AUDIT_DIR=/tmp/fieldshift-comparison-audit \
AUTH_API_PORT=8002 AUTH_FRONTEND_ORIGIN=http://localhost:5175 \
uv run python -m tests.browser_auth_server
```

It uses the local test Postgres server on port 5433. Set `TEST_DATABASE_ADMIN_URL` if needed.
The database is removed when the server shuts down normally. Do not point this fixture server at
production data.

Start a separate frontend from `frontend/`:

```bash
VITE_API_BASE_URL=/v1 VITE_API_PROXY_TARGET=http://127.0.0.1:8002 \
VITE_USE_MOCKS=0 npm run dev -- --port 5175 --strictPort
```

Then, from `frontend/`:

```bash
CHROMIUM_PATH=/usr/bin/chromium npm run test:comparison:browser
```

Omit `CHROMIUM_PATH` when using Playwright's installed browser. `COMPARISON_BASE_URL` and
`COMPARISON_AUDIT_DIR` override the browser origin and artifact directory. Results and screenshots default
to `/tmp/fieldshift-comparison-audit`.

## Limits

The area-ranking frontend and ranked-map-to-comparison interaction do not exist yet; those routes were
verified at API level. This check does not prove production-scale ranking performance or map rendering
with the full survey tile set. The disposable server uses synthetic boundaries and tile fixtures.
Real sources sometimes return missing slope or soil data; the UI preserves their reasons.
Firefox, Safari and physical phones were not tested.
