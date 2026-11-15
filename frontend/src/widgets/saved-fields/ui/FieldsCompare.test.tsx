import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as renderComponent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router";
import type { FieldComparison, SavedFieldComparisonRequest } from "@/entities/comparison";
import type { SavedField } from "@/entities/saved-field";
import { setAccessToken } from "@/shared/api";
import { env } from "@/shared/config";
import { renderRoutes } from "@/shared/lib/test";
import { DEFAULT_POINT, selectionFor } from "@/shared/mocks";
import { FieldsCompare } from "./FieldsCompare";

const server = setupServer();
beforeAll(() => server.listen());
afterEach(() => { server.resetHandlers(); setAccessToken(null); });
afterAll(() => server.close());
const endpoint = `${env.apiBaseUrl}/comparisons/saved-fields`;
const selection = selectionFor(DEFAULT_POINT, "coordinates");
const fields: SavedField[] = ["North", "South"].map((name, index) => ({
  id: `e1980477-f2e4-4da2-a34b-e0b3422f4da${index}`, name,
  field_id: selection.field_id, geometry: selection.geometry, centroid: selection.anchor,
  area_ha: selection.area_ha, state: "IA", crop_history: null, info: null, info_fetched_at: null,
  created_at: "2026-11-14T12:00:00Z", updated_at: "2026-11-14T12:00:00Z",
}));

function response(): FieldComparison {
  return {
    generated_at: "2026-11-15T12:00:00Z", plan: { rotation: ["corn", "soybean"], horizon_years: 2 },
    fields: fields.map((f, i) => ({
      saved_field_id: f.id, label: i === 0 ? "A" : "B", name: f.name, field_id: f.field_id,
      state: "IA", county: null, anchor: f.centroid, boundary_type: "estimated_csb", area_ha: f.area_ha,
      rent: { per_acre: 274, source: "state_baseline", is_placeholder: false }, budget: null,
      net_return_per_acre: { low: -80, base: -20, high: 40 }, net_return_field: null,
      break_even_rent_per_acre: { low: 194, base: 254, high: 314 },
      history: { source: "none", years_recorded: 0, first_year: null, latest_year: null, latest_crop: null,
        corn_years: 0, soybean_years: 0, other_years: 0, distinct_crops: 0, corn_in_a_row: 0, pattern: "unknown" },
      strengths: [], cautions: ["Inspect drainage before renting."], data_as_of: null, info_as_of: null,
    })),
    rows: [
      { key: "soil_ph", label: "Soil pH", group: "soil", unit: "pH", better: "target", target: { min: 6, max: 7 },
        // Deliberately reverse cells: render by id, and trust the server's winner even when values tie.
        cells: [...fields].reverse().map((f) => ({ saved_field_id: f.id, value: 6.4, quality: "measured" })),
        best: [fields[1]!.id], same_for_all: false, note: "Check local soil tests." },
      { key: "rain", label: "Annual rain", group: "climate", unit: "mm", better: "none",
        cells: fields.map((f) => ({ saved_field_id: f.id, value: 25.4, quality: "modeled" })), best: [], same_for_all: true },
      { key: "missing", label: "Organic matter", group: "soil", unit: "%", better: "higher",
        cells: fields.map((f) => ({ saved_field_id: f.id, value: null, quality: "unavailable", note: "Soil source is down." })),
        best: [], same_for_all: false },
      { key: "net_return_per_acre", label: "Return after rent", group: "money", unit: "USD/acre/year", better: "higher",
        cells: fields.map((f) => ({ saved_field_id: f.id, value: -20, quality: "estimated" })), best: [], same_for_all: true },
    ], best: { net_return: [], soil_productivity: [fields[1]!.id], rent_value: [] },
    warnings: ["Illustrative state budgets; soil does not predict yield."], disclaimer: "Inspect each field before signing a lease.",
  };
}
const render = () => renderRoutes([{ path: "/", element: <FieldsCompare fields={fields} userId="farmer-1" /> }], "/");
const row = (name: string) => within(screen.getByRole("rowheader", { name: new RegExp(name) }).closest('[role="row"]')!);

it("requests one authenticated comparison and renders server winners, missing reasons, units and warnings", async () => {
  setAccessToken("test-token");
  let calls = 0;
  server.use(http.post(endpoint, async ({ request }) => {
    calls++;
    expect(request.headers.get("Authorization")).toBe("Bearer test-token");
    expect(await request.json()).toEqual({ saved_field_ids: fields.map((f) => f.id) });
    return HttpResponse.json(response());
  }));
  render();
  await screen.findByRole("table");
  expect(calls).toBe(1);
  expect(screen.getByText("Illustrative state budgets; soil does not predict yield.")).toBeInTheDocument();
  expect(row("Soil pH").getByText("Best 6.0 to 7.0")).toBeInTheDocument();
  const cells = row("Soil pH").getAllByRole("cell");
  expect(within(cells[0]!).queryByText("Best")).not.toBeInTheDocument();
  expect(within(cells[1]!).getByText("Best")).toBeInTheDocument();
  expect(row("Annual rain").getAllByText("1.0 in")).toHaveLength(2);
  expect(row("Organic matter").getAllByText("Not available")).toHaveLength(2);
  expect(row("Organic matter").getAllByText("Soil source is down.")).toHaveLength(2);
  expect(row("Return after rent").getAllByText("-$20.00 / acre / year (loss)")).toHaveLength(2);
  expect(screen.getByText("Inspect each field before signing a lease.")).toBeInTheDocument();
});

it("submits zero rent and one shared plan, retaining previous results while loading", async () => {
  const bodies: SavedFieldComparisonRequest[] = [];
  server.use(http.post(endpoint, async ({ request }) => {
    bodies.push(await request.json() as SavedFieldComparisonRequest);
    if (bodies.length > 1) await delay(150);
    return HttpResponse.json(response());
  }));
  render(); await screen.findByRole("table");
  await userEvent.type(screen.getByLabelText("A · North asking rent"), "0");
  await userEvent.selectOptions(screen.getByLabelText("Shared crop rotation"), "soybean");
  await userEvent.selectOptions(screen.getByLabelText("Budget horizon"), "3");
  expect(bodies).toHaveLength(1); // Editing does not spend requests until Update.
  await userEvent.click(screen.getByRole("button", { name: "Update comparison" }));
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Previous results");
  await screen.findByRole("button", { name: "Update comparison" });
  expect(bodies[1]).toEqual({ saved_field_ids: fields.map((f) => f.id), rent_per_acre: { [fields[0]!.id]: 0 },
    plan: { rotation: ["soybean"], horizon_years: 3 } });
});

it.each(["-1", "5001"])("blocks invalid rent %s without sending a request", async (rent) => {
  let calls = 0;
  server.use(http.post(endpoint, () => { calls++; return HttpResponse.json(response()); }));
  render(); await screen.findByRole("table");
  await userEvent.type(screen.getByLabelText("A · North asking rent"), rent);
  await userEvent.click(screen.getByRole("button", { name: "Update comparison" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Enter rents from $0 to $5,000");
  expect(calls).toBe(1);
});

it("keeps previous results on a failed update and supports retry", async () => {
  let calls = 0;
  server.use(http.post(endpoint, () => ++calls === 2
    ? HttpResponse.json({ error: { code: "INTERNAL_ERROR", message: "Try later." } }, { status: 503 })
    : HttpResponse.json(response())));
  render(); await screen.findByRole("table");
  await userEvent.click(screen.getByRole("button", { name: "Update comparison" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Try later.");
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getByText("Showing the previous comparison. The latest update failed.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByRole("button", { name: "Update comparison" });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(calls).toBe(3);
});

it.each([401, 404, 429])("handles HTTP %s without retries or misleading results", async (status) => {
  let calls = 0;
  server.use(http.post(endpoint, () => {
    calls++;
    return HttpResponse.json({ error: { code: status === 401 ? "UNAUTHORIZED" : status === 404 ? "NOT_FOUND" : "RATE_LIMITED",
      message: "Cannot compare." } }, { status, headers: status === 429 ? { "Retry-After": "2" } : {} });
  }));
  render();
  await screen.findByRole("alert");
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(calls).toBe(1);
  if (status === 401) expect(screen.getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/sign-in?next=%2Fmy-fields");
  if (status === 404) expect(screen.getByText("Return to Saved fields and select the fields again.")).toBeInTheDocument();
  if (status === 429) {
    expect(screen.getByRole("alert")).toHaveTextContent("Try again in 2 seconds");
    expect(screen.getByRole("button", { name: "Try again" })).toBeDisabled();
  }
});

it("clears rate-limit cooldown when an external refetch succeeds", async () => {
  let calls = 0;
  server.use(http.post(endpoint, () => ++calls === 1
    ? HttpResponse.json({ error: { code: "RATE_LIMITED", message: "Wait." } }, { status: 429, headers: { "Retry-After": "60" } })
    : HttpResponse.json(response())));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  renderComponent(<QueryClientProvider client={client}><MemoryRouter>
    <FieldsCompare fields={fields} userId="farmer-1" />
  </MemoryRouter></QueryClientProvider>);
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "Update comparison" })).toBeDisabled();
  await client.refetchQueries({ queryKey: ["field-comparison"] });
  await screen.findByRole("table");
  await waitFor(() => expect(screen.getByRole("button", { name: "Update comparison" })).toBeEnabled());
});
