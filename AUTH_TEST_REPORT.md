# Login and authentication browser audit

Date: 2026-11-15

## Result

Seven authentication bugs were reproduced and fixed. All 31 final Chromium desktop/mobile browser cases passed, with no uncaught browser errors. Results are recorded in `/tmp/fieldshift-auth-audit/browser-results.json`.

| Validation | Result |
| --- | --- |
| Chromium desktop/mobile browser suite | 31 cases passed |
| Frontend unit/integration suite | 146 tests passed across 28 files |
| Backend auth, password recovery, and saved-field suites | 62 tests passed |
| Production frontend build | Passed |
| Frontend architecture lint | Passed |
| Browser fixture Python lint | Passed |

## Bugs fixed

| Bug | Cause and fix | Regression proof |
| --- | --- | --- |
| Startup refresh could erase a successful login/signup | A late refresh failure cleared newer authentication state. Auth operations now run in order. | Delayed startup response during signup; session unit test |
| Refresh could sign the user back in after logout | An in-flight rotation could finish after logout and restore state/cookies. Logout now waits for rotation before revoking the current cookie. Explicit session clearing also invalidates in-flight refresh results. | Delayed refresh during logout; cookie/state checks; session unit tests |
| Concurrent tabs could lose authentication | Tabs raced to consume the same single-use refresh cookie. Web Locks now serialize cookie mutations across supported tabs; a local queue orders operations within each tab. | Three tabs restore concurrently against the real API |
| Failed logout pretended to succeed | Session state cleared and navigation continued despite a failed logout request, causing an uncaught rejection and allowing later session restoration. Failed logout now shows an error, keeps the session visible, and supports retry. | Browser network failure/retry; account-menu and session tests |
| Unchecked “Keep me signed in” preference was erased | The first new tab removed the preference before logout completed. New tabs now retain the preference; successful explicit logout clears the live-tab marker. | Reload plus two new tabs; session test |
| Signup lost the protected return destination | Auth-form links dropped `next`, and signup never used it. Both forms now preserve safe local destinations, and signup returns to the requested page. | Browser sign-in/signup round trip and signup; router and unsafe-target tests |
| Revoked access left protected UI looking signed in | Protected API 401 responses did not update session state. A rejection of the current token now clears the session. Wrong-password auth errors and older-token responses do not clear newer sessions. | Password change/reset in another browser context; session unit tests |

## Browser coverage

The suite exercises real frontend forms, the real FastAPI auth endpoints, PostgreSQL, and browser cookies. It covers:

- Signup validation, agreement, duplicate accounts, normalized email, successful login, wrong credentials, and unknown accounts.
- Protected routes; safe and unsafe return targets; switching between signup and sign-in.
- HttpOnly cookie scope, token storage, reload restoration, concurrent tabs, scheduled refresh, refresh-cookie rotation/replay, and invalid cookies.
- Remembered and nonremembered sessions; successful logout; delayed startup/refresh responses; failed logout and retry.
- Login network failure, rate-limit response, server failure, and successful retries.
- Password visibility; current-password and confirmation checks; password changes; rejection of old passwords; revocation of other sessions.
- Recovery confirmation for known/unknown accounts, generated email links, URL token removal, mismatched confirmation, successful reset, token reuse rejection, and invalid links.
- Mobile signup, session restoration, account menu, password form, logout, reset validation, screenshots, and viewport overflow checks at 390 × 844.

Backend tests additionally cover expired/tampered access tokens, expired reset links, SMTP behavior, authorization, and token revocation. Browser refresh timing uses Playwright's clock; it does not wait 15 real minutes.

## Environment and limits

The existing development backend returns HTTP 502 with `Password reset email is unavailable. Try again later.` because SMTP credentials are absent. Recovery was tested with an isolated real backend and a local mail-capture adapter. Actual Brevo authentication and inbox delivery remain unverified and require working SMTP credentials.

Browser tests used Chromium 155.0.8059.84, with desktop and mobile emulation. Firefox, Safari, and physical mobile devices were not tested. Cross-tab serialization uses Web Locks where available; the fallback serializes operations within one tab.

The isolated fixture raises password rate limits so repeated negative cases can run from one local IP. Production rate limits remain unchanged. Browser 429 handling and backend rate-limit behavior have separate coverage.

Pre-existing workspace changes were preserved. Thirteen audit-created accounts were removed from the existing development database. The browser fixture uses a disposable database, dropped on shutdown. Captured mail stays outside the repository with file permissions `0600`.

## Reproduce

From `backend`, start the disposable API:

```bash
uv run python -m tests.browser_auth_server
```

From `frontend`, start a separate Vite instance:

```bash
VITE_API_BASE_URL=http://localhost:8002/v1 npm run dev -- --host localhost --port 5174 --strictPort
```

In another terminal, from `frontend`:

```bash
CHROMIUM_PATH=/usr/bin/chromium \
AUTH_BASE_URL=http://localhost:5174 \
AUTH_API_BASE_URL=http://localhost:8002/v1 \
AUTH_MAIL_CAPTURE_PATH=/tmp/fieldshift-auth-audit/mail.jsonl \
npm run test:auth:browser
```

Run `npm ci` first if dependencies are missing. Omit `CHROMIUM_PATH` to use a Playwright-installed Chromium. Stop the fixture API with Ctrl+C to drop its scratch database.

Browser results and mobile screenshots are written under `/tmp/fieldshift-auth-audit/`. Reset email captures contain bearer secrets and should remain local.
