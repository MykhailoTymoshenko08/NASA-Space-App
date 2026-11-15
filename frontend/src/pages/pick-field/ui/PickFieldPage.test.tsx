import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import * as fieldApi from "@/entities/field";
import type { FieldSelection } from "@/shared/api";
import { env } from "@/shared/config";
import { renderRoutes } from "@/shared/lib/test";
import { DEFAULT_POINT, handlers, selectionFor } from "@/shared/mocks";
import type { MapHit } from "@/shared/ui/map";
import { PickFieldPage } from "./PickFieldPage";

// MapLibre needs WebGL, which jsdom does not have. The map is covered by its own props here.
vi.mock("@/shared/ui/map", async () => {
  const { forwardRef } = await import("react");
  return {
    isNarrowScreen: () => false,
    tapWord: () => "Click",
    ZOOM: { countyLines: 5.5, county: 7, township: 8, sections: 11 },
    COUNTY_FIT_MIN_ZOOM: 8.5,
    FieldMap: forwardRef(function FakeMap(props: { ariaLabel: string; onClick: (hit: MapHit) => void }, _ref) {
      const hit = (id: string): MapHit => ({
        point: { lat: 41.5868, lon: -93.625 }, zoom: 14, state: null, county: null, township: null,
        outsideFocus: false, field: { field_id: id, crop_class: "Corn", area_ha: 10 },
      });
      return (
        <div role="application" aria-label={props.ariaLabel}>
          <button onClick={() => props.onClick(hit("field-a"))}>Pick field A</button>
          <button onClick={() => props.onClick(hit("field-b"))}>Pick field B</button>
        </div>
      );
    }),
  };
});

const server = setupServer(...handlers);
beforeAll(() => server.listen());
afterEach(() => { server.resetHandlers(); vi.restoreAllMocks(); });
afterAll(() => server.close());

const renderPage = () =>
  renderRoutes(
    [
      { path: "/pick-field", element: <PickFieldPage /> },
      { path: "/analysis", element: <p>Setup page</p> },
      { path: "/field", element: <p>Field page</p> },
    ],
    "/pick-field",
  );

describe("PickFieldPage", () => {
  it("starts on the whole country and follows the state and county the user chooses", async () => {
    renderPage();
    expect(screen.getByLabelText("Map of the United States")).toBeInTheDocument();
    const state = screen.getByLabelText("State");
    await screen.findByRole("option", { name: "Illinois" }, { timeout: 5000 });
    expect(state).toHaveDisplayValue("Choose a state");
    expect(screen.getByLabelText("County")).toHaveDisplayValue("Choose a state first");
    expect(screen.getByText(/available in Illinois, Iowa and Nebraska for now/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get analysis" })).toBeDisabled();

    await userEvent.selectOptions(state, "Illinois");
    expect(screen.getByLabelText("Map of Illinois")).toBeInTheDocument();
    await screen.findByRole("option", { name: "Champaign" }, { timeout: 5000 });
    expect(screen.getByLabelText("County")).toHaveDisplayValue("Choose a county");

    await userEvent.selectOptions(screen.getByLabelText("County"), "Champaign");
    expect(screen.getByLabelText("Map of Champaign County, IL")).toBeInTheDocument();
  });

  it("resolves pasted coordinates into a selected field", async () => {
    const router = renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Link or coordinates" }));
    await userEvent.type(screen.getByLabelText(/Google Maps link/), "41.5868, -93.6250");
    expect(
      await screen.findByText("Found 41.5868, -93.6250. We matched it to the nearest estimated field area.", undefined, {
        timeout: 3000,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Picked from: Link or coordinates")).toBeInTheDocument();
    expect(screen.getByText(/About 80 acres \(32.4 ha\), Polk County, IA/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("link", { name: /Get analysis/ }));
    expect(router.state.location.pathname).toBe("/analysis");
  });

  it("explains input it cannot read", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Link or coordinates" }));
    await userEvent.type(screen.getByLabelText(/Google Maps link/), "my back forty");
    expect(await screen.findByText(/We could not read that/, undefined, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByLabelText(/Google Maps link/)).toHaveAttribute("aria-invalid", "true");
  });

  it("clears the old selection as soon as the location input changes", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Link or coordinates" }));
    const input = screen.getByLabelText(/Google Maps link/);
    await userEvent.type(input, "41.5868, -93.6250");
    await screen.findByRole("link", { name: "Get analysis" }, { timeout: 3000 });
    fireEvent.change(input, { target: { value: "x" } });
    expect(screen.getByRole("button", { name: "Get analysis" })).toBeDisabled();
    expect(screen.queryByText("Picked from: Link or coordinates")).not.toBeInTheDocument();

    fireEvent.change(input, { target: { value: "41.5868, -93.6250" } });
    await screen.findByRole("link", { name: "Get analysis" }, { timeout: 3000 });
    // A replacement that is still resolving must not reactivate the old field either.
    let release!: () => void;
    let started!: () => void;
    const requested = new Promise<void>((resolve) => { started = resolve; });
    const response = new Promise<void>((resolve) => { release = resolve; });
    server.use(http.post(`${env.apiBaseUrl}/locations/resolve`, async () => {
      started();
      await response;
      return HttpResponse.json({ input_kind: "plain_coordinates", point: DEFAULT_POINT,
        selection: selectionFor(DEFAULT_POINT, "coordinates") });
    }));
    fireEvent.change(input, { target: { value: "41.6, -93.6" } });
    await requested;
    expect(screen.getByRole("button", { name: "Get analysis" })).toBeDisabled();
    release();
    expect(await screen.findByRole("link", { name: "Get analysis" })).toBeInTheDocument();
  });

  it("keeps the last map click even when an aborted request still returns", async () => {
    let finishFirst!: (value: FieldSelection) => void;
    const first = new Promise<FieldSelection>((resolve) => { finishFirst = resolve; });
    const selection = selectionFor(DEFAULT_POINT, "map_click");
    const fetch = vi.spyOn(fieldApi, "fetchField")
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce({ ...selection, field_id: "field-b" });
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Pick field A" }));
    await userEvent.click(screen.getByRole("button", { name: "Pick field B" }));
    expect(await screen.findByRole("link", { name: "Get analysis" })).toHaveAttribute("href",
      expect.stringContaining("field_id=field-b"));
    expect(fetch.mock.calls[0]![1]!.aborted).toBe(true);
    await act(async () => finishFirst({ ...selection, field_id: "field-a" }));
    expect(screen.getByRole("link", { name: "Get analysis" })).toHaveAttribute("href",
      expect.stringContaining("field_id=field-b"));
  });

  it("discards a pending field when the user changes state", async () => {
    let finish!: (value: FieldSelection) => void;
    const fetch = vi.spyOn(fieldApi, "fetchField").mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    renderPage();
    await screen.findByRole("option", { name: "Illinois" });
    await userEvent.click(screen.getByRole("button", { name: "Pick field A" }));
    await userEvent.selectOptions(screen.getByLabelText("State"), "Illinois");
    expect(fetch.mock.calls[0]![1]!.aborted).toBe(true);
    await act(async () => finish(selectionFor(DEFAULT_POINT, "map_click")));
    expect(screen.getByRole("button", { name: "Get analysis" })).toBeDisabled();
  });
});
