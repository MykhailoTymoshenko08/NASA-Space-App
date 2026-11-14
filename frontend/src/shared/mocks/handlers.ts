/**
 * MSW handlers typed from the generated contract types, so contract drift breaks the build.
 * Demo data only. Scenarios:
 *  - inside Iowa, Illinois or Nebraska    : estimated field area (snapped from a point, exact by id)
 *  - elsewhere in the contiguous US       : 300 m buffered circle, no field id
 *  - lat >= 45                            : SMAP soil moisture unavailable; analyses fail
 *  - outside the contiguous US            : 422 OUTSIDE_COVERAGE
 *  - field_id "csb_missing"               : 404 NOT_FOUND
 * Auth keeps demo accounts in localStorage; the refresh "cookie" is simulated in memory/localStorage.
 */
import { delay, http, HttpResponse, type AnyHandler } from "msw";
import type { components } from "@/shared/api";
import { env } from "@/shared/config";
import {
  COUNTIES,
  DEFAULT_POINT,
  inConus,
  metricsFor,
  pointOfFieldId,
  resultFor,
  selectionFor,
  STATES,
} from "./data";

type S = components["schemas"];
type LatLon = S["LatLon"];

const url = (path: string) => `${env.apiBaseUrl}${path}`;
const isTest = import.meta.env.MODE === "test";
const wait = (ms = 700) => delay(isTest ? 0 : ms);
const requestId = () => `mock-${Math.random().toString(36).slice(2, 10)}`;

function errorResponse(status: number, code: S["ErrorCode"], message: string, headers: Record<string, string> = {}) {
  const id = requestId();
  return HttpResponse.json<S["ErrorResponse"]>(
    { error: { code, message, request_id: id } },
    { status, headers: { "X-Request-Id": id, ...headers } },
  );
}

/* ---------- locations ---------- */

type Parsed = { kind: S["ResolvedLocation"]["input_kind"]; point: LatLon } | { error: S["ErrorCode"] };

function parseInput(raw: string): Parsed {
  const t = raw.trim();
  let m = t.match(/^(-?\d{1,3}(?:\.\d+)?)\s*°?\s*([NS])?\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*°?\s*([EW])?$/i);
  if (m) {
    let lat = parseFloat(m[1]!);
    let lon = parseFloat(m[3]!);
    if (m[2]?.toUpperCase() === "S") lat = -Math.abs(lat);
    if (m[4]?.toUpperCase() === "W") lon = -Math.abs(lon);
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return { error: "UNPARSEABLE_INPUT" };
    return { kind: "plain_coordinates", point: { lat, lon } };
  }
  const google = /google\.[a-z.]+\/maps|maps\.google|goo\.gl/i.test(t);
  const apple = /maps\.apple\.com|apple\.co/i.test(t);
  if (google || apple) {
    m =
      t.match(/@(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)/) ||
      t.match(/[?&](?:ll|q|sll|center)=(-?\d{1,3}\.\d+)(?:,|%2C)(-?\d{1,3}\.\d+)/i) ||
      t.match(/!3d(-?\d{1,3}\.\d+)!4d(-?\d{1,3}\.\d+)/);
    const kind = google ? "google_maps_url" : "apple_maps_url";
    if (m) return { kind, point: { lat: parseFloat(m[1]!), lon: parseFloat(m[2]!) } };
    // Short Google links are "followed" to the demo point; Apple short links have no coordinates.
    if (/maps\.app\.goo\.gl|goo\.gl\/maps/i.test(t)) return { kind, point: DEFAULT_POINT };
    return { error: "UNSUPPORTED_LINK" };
  }
  return { error: "UNPARSEABLE_INPUT" };
}

/* ---------- analyses ---------- */

type Job = { created: number; selection: S["FieldSelection"]; fail: boolean };
const jobs = new Map<string, Job>();
const JOB_MS = isTest ? 0 : 7000;
const STAGES: [number, string][] = [
  [0, "Queued"],
  [10, "Fetching soil moisture history"],
  [40, "Reading your crop history"],
  [70, "Scoring rotation strategies"],
  [90, "Writing your report"],
];

function jobView(id: string, job: Job): S["AnalysisJob"] {
  const elapsed = Date.now() - job.created;
  const pct = JOB_MS === 0 ? 100 : Math.min(100, Math.round((elapsed / JOB_MS) * 100));
  const stage = [...STAGES].reverse().find(([p]) => pct >= p)?.[1] ?? "Queued";
  const base = { job_id: id, created_at: new Date(job.created).toISOString() };
  if (pct < 100) {
    return { ...base, status: pct === 0 ? "queued" : "running", finished_at: null, progress: { percent: pct, stage } };
  }
  const finished_at = new Date(job.created + JOB_MS).toISOString();
  if (job.fail) {
    return {
      ...base,
      status: "failed",
      finished_at,
      progress: { percent: 100, stage: "Stopped" },
      error: {
        code: "UPSTREAM_DATA_UNAVAILABLE",
        message: "Soil moisture data from NASA did not respond in time.",
        request_id: requestId(),
      },
    };
  }
  return { ...base, status: "succeeded", finished_at, progress: { percent: 100, stage: "Done" }, result: resultFor(job.selection) };
}

/* ---------- auth ---------- */

type Account = { id: string; email: string; password: string; created_at: string };
const ACCOUNTS_KEY = "fieldline.mock.accounts";
const SESSION_KEY = "fieldline.mock.refresh";
const memory = new Map<string, string>();
const store = {
  get: (k: string) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return memory.get(k) ?? null;
    }
  },
  set: (k: string, v: string | null) => {
    try {
      if (v === null) localStorage.removeItem(k);
      else localStorage.setItem(k, v);
    } catch {
      if (v === null) memory.delete(k);
      else memory.set(k, v);
    }
  },
};
const accounts = (): Account[] => JSON.parse(store.get(ACCOUNTS_KEY) ?? "[]") as Account[];
const userOf = (a: Account): S["User"] => ({ id: a.id, email: a.email, created_at: a.created_at });
const tokensFor = (a: Account): S["AuthTokens"] => {
  store.set(SESSION_KEY, a.id);
  return { access_token: `mock.${a.id}`, token_type: "bearer", expires_in: 900, user: userOf(a) };
};

export const handlers: AnyHandler[] = [
  http.get(url("/health"), () => HttpResponse.json({ status: "ok" as const })),

  http.get(url("/meta/coverage"), () =>
    HttpResponse.json<S["Coverage"]>({
      bounds: [-104.05, 36.97, -87.5, 43.5],
      supported_states: ["IA", "IL", "NE"],
      field_data_version: "csb2018-2025-ia-il-ne",
      field_boundary_source: {
        name: "USDA Crop Sequence Boundaries",
        edition: "2018-2025",
        boundary_type: "estimated_csb",
        attribution: null,
      },
      field_tiles: {
        format: "pmtiles",
        unit: "estimated_csb",
        min_zoom: 12,
        max_zoom: 14,
        url_template: url("/tiles/fields.pmtiles"),
        regions: STATES.map((s) => ({ name: s.name, bbox: s.bbox })),
      },
    }),
  ),

  // No vector tiles in demo mode: boundaries answer "empty tile", the field file is missing.
  http.get(url("/tiles/boundaries/:z/:x/:y.mvt"), () => new HttpResponse(null, { status: 204 })),
  http.all(url("/tiles/fields.pmtiles"), () => errorResponse(404, "NOT_FOUND", "No field tiles in demo mode.")),

  http.get(url("/geo/states"), () => HttpResponse.json({ items: STATES })),
  http.get(url("/geo/states/:fips/counties"), ({ params }) => {
    if (!STATES.some((s) => s.fips === params.fips)) return errorResponse(404, "NOT_FOUND", "State not supported.");
    return HttpResponse.json({ items: COUNTIES.filter((c) => c.state_fips === params.fips) });
  }),
  http.get(url("/geo/counties/:fips"), ({ params }) => {
    const c = COUNTIES.find((x) => x.fips === params.fips);
    return c ? HttpResponse.json(c) : errorResponse(404, "NOT_FOUND", "No county with that FIPS code.");
  }),

  http.post<never, { input: string }>(url("/locations/resolve"), async ({ request }) => {
    await wait(500);
    const { input } = await request.json();
    const parsed = parseInput(input ?? "");
    if ("error" in parsed) return errorResponse(422, parsed.error, "Could not read a location from that input.");
    if (!inConus(parsed.point)) return errorResponse(422, "OUTSIDE_COVERAGE", "That point is outside the contiguous US.");
    const source: S["SelectionSource"] = parsed.kind === "plain_coordinates" ? "coordinates" : "location_link";
    return HttpResponse.json<S["ResolvedLocation"]>({
      input_kind: parsed.kind,
      point: parsed.point,
      selection: selectionFor(parsed.point, source),
    });
  }),

  http.post<never, { point: LatLon; source?: S["SelectionSource"] }>(url("/fields/resolve"), async ({ request }) => {
    await wait(300);
    const { point, source } = await request.json();
    if (!inConus(point)) return errorResponse(422, "OUTSIDE_COVERAGE", "That point is outside the contiguous US.");
    return HttpResponse.json(selectionFor(point, source ?? "map_click"));
  }),

  http.get(url("/fields/:fieldId"), async ({ params }) => {
    await wait(300);
    const p = pointOfFieldId(String(params.fieldId));
    if (!p) return errorResponse(404, "NOT_FOUND", "No field with that id.");
    return HttpResponse.json(selectionFor(p, "landing_map_click", "id"));
  }),

  http.post<never, { selection: S["SelectionRef"] }>(url("/snapshots"), async ({ request }) => {
    await wait(900);
    const ref = (await request.json()).selection;
    let point: LatLon;
    let how: "id" | "point" = "point";
    if ("field_id" in ref) {
      const p = pointOfFieldId(ref.field_id);
      if (!p) return errorResponse(404, "NOT_FOUND", "No field with that id.");
      point = p;
      how = "id";
    } else {
      point = ref.point;
    }
    if (!inConus(point)) return errorResponse(422, "OUTSIDE_COVERAGE", "That point is outside the contiguous US.");
    return HttpResponse.json<S["Snapshot"]>({
      selection: selectionFor(point, "coordinates", how),
      generated_at: new Date().toISOString(),
      cached: false,
      metrics: metricsFor(point),
    });
  }),

  http.post<never, S["AnalysisRequest"]>(url("/analyses"), async ({ request }) => {
    await wait(400);
    const body = await request.json();
    const ref = body.selection;
    let point: LatLon | null;
    let how: "id" | "point" = "point";
    if ("field_id" in ref) {
      point = pointOfFieldId(ref.field_id);
      how = "id";
    } else point = ref.point;
    if (!point) return errorResponse(404, "NOT_FOUND", "No field with that id.");
    if (!inConus(point)) return errorResponse(422, "OUTSIDE_COVERAGE", "That point is outside the contiguous US.");
    const id = crypto.randomUUID();
    const job: Job = { created: Date.now(), selection: selectionFor(point, "coordinates", how), fail: point.lat >= 45 };
    jobs.set(id, job);
    const view = jobView(id, job);
    return HttpResponse.json<S["AnalysisJob"]>(
      { ...view, status: "queued", progress: { percent: 0, stage: "Queued" }, result: undefined, error: undefined },
      { status: 202, headers: { Location: url(`/analyses/${id}`) } },
    );
  }),

  http.get(url("/analyses/:jobId"), async ({ params }) => {
    await wait(150);
    const id = String(params.jobId);
    const job = jobs.get(id);
    if (!job) return errorResponse(404, "NOT_FOUND", "No analysis with that id. It may have expired.");
    return HttpResponse.json(jobView(id, job));
  }),

  http.post<never, S["RegisterRequest"]>(url("/auth/register"), async ({ request }) => {
    await wait(400);
    const { email = "", password = "" } = await request.json();
    const e = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e) || password.length < 8 || !/\d/.test(password) || !/\p{L}/u.test(password)) {
      return errorResponse(422, "VALIDATION_ERROR", "Check the email and password rules.");
    }
    if (accounts().some((a) => a.email === e)) return errorResponse(409, "EMAIL_TAKEN", "An account with this email already exists.");
    const a: Account = { id: crypto.randomUUID(), email: e, password, created_at: new Date().toISOString() };
    store.set(ACCOUNTS_KEY, JSON.stringify([...accounts(), a]));
    return HttpResponse.json(tokensFor(a), { status: 201 });
  }),

  http.post<never, S["LoginRequest"]>(url("/auth/login"), async ({ request }) => {
    await wait(400);
    const { email = "", password = "" } = await request.json();
    const a = accounts().find((x) => x.email === email.trim().toLowerCase() && x.password === password);
    if (!a) return errorResponse(401, "UNAUTHORIZED", "Email or password is not right.", { "WWW-Authenticate": "Bearer" });
    return HttpResponse.json(tokensFor(a));
  }),

  http.post(url("/auth/refresh"), () => {
    const id = store.get(SESSION_KEY);
    const a = accounts().find((x) => x.id === id);
    if (!a) return errorResponse(401, "UNAUTHORIZED", "No session.");
    return HttpResponse.json(tokensFor(a));
  }),

  http.post(url("/auth/logout"), () => {
    store.set(SESSION_KEY, null);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(url("/me"), ({ request }) => {
    const token = request.headers.get("Authorization")?.replace(/^Bearer mock\./, "");
    const a = accounts().find((x) => x.id === token);
    return a ? HttpResponse.json(userOf(a)) : errorResponse(401, "UNAUTHORIZED", "Sign in first.");
  }),
];
