import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type { SavedField } from "@/entities/saved-field";
import type { Metric, Snapshot } from "@/shared/api";
import { env } from "@/shared/config";
import { renderRoutes } from "@/shared/lib/test";
import { DEFAULT_POINT, selectionFor } from "@/shared/mocks";
import { FieldsCompare } from "./FieldsCompare";

const server = setupServer();
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const selection = selectionFor(DEFAULT_POINT, "coordinates");
const saved: SavedField = {
  id: "e1980477-f2e4-4da2-a34b-e0b3422f4dad",
  name: "Test field",
  field_id: selection.field_id,
  geometry: selection.geometry,
  centroid: selection.anchor,
  area_ha: selection.area_ha,
  state: "IA",
  crop_history: selection.crop_history ?? null,
  info: null,
  info_fetched_at: null,
  created_at: "2026-11-14T12:00:00Z",
  updated_at: "2026-11-14T12:00:00Z",
};

function renderWithWetness(value: number | null) {
  const metric: Metric = {
    key: "soil_wetness_surface",
    label: "Surface soil wetness (modeled, 30-day mean)",
    category: "moisture",
    value,
    unit: "fraction",
    quality: value === null ? "unavailable" : "modeled",
    source: { dataset: "NASA POWER Daily (GEOS-IT / MERRA-2 meteorology)", provider: "NASA" },
    resolution_m: 55_000,
  };
  server.use(
    http.post(`${env.apiBaseUrl}/snapshots`, async ({ request }) => {
      expect(await request.json()).toEqual({ selection: { field_id: saved.field_id } });
      return HttpResponse.json<Snapshot>({
        selection,
        generated_at: "2026-11-14T12:00:00Z",
        cached: false,
        metrics: [metric],
      });
    }),
  );
  renderRoutes([{ path: "/", element: <FieldsCompare fields={[saved]} /> }], "/");
  return within(screen.getByRole("rowheader", { name: /Surface soil wetness/ }).closest('[role="row"]')!);
}

describe("FieldsCompare", () => {
  it.each([0.64, 0])("shows backend surface wetness %s as a modeled fraction", async (value) => {
    const row = renderWithWetness(value);
    expect(await row.findByText(value.toFixed(2))).toBeInTheDocument();
    expect(row.getByText("Modeled")).toBeInTheDocument();
    expect(row.queryByText("m³/m³")).not.toBeInTheDocument();
    expect(row.queryByText("Not available")).not.toBeInTheDocument();
  });

  it("keeps unavailable wetness unavailable", async () => {
    const row = renderWithWetness(null);
    expect(await within(row.getByRole("cell")).findByText("Not available")).toBeInTheDocument();
    expect(row.queryByText("0.00")).not.toBeInTheDocument();
  });
});
