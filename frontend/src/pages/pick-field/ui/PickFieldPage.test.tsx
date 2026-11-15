import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { renderRoutes } from "@/shared/lib/test";
import { handlers } from "@/shared/mocks";
import { PickFieldPage } from "./PickFieldPage";

// MapLibre needs WebGL, which jsdom does not have. The map is covered by its own props here.
vi.mock("@/shared/ui/map", async () => {
  const { forwardRef } = await import("react");
  return {
    isNarrowScreen: () => false,
    tapWord: () => "Click",
    ZOOM: { countyLines: 5.5, county: 7, township: 8, sections: 11 },
    COUNTY_FIT_MIN_ZOOM: 8.5,
    FieldMap: forwardRef(function FakeMap(props: { ariaLabel: string }, _ref) {
      return <div role="application" aria-label={props.ariaLabel} />;
    }),
  };
});

const server = setupServer(...handlers);
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
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
});
