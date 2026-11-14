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
  it("fills state and county from the API and points the map at the county", async () => {
    renderPage();
    expect(await screen.findByLabelText("Map of Champaign County, IL", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByLabelText("State")).toHaveDisplayValue("Illinois");
    expect(screen.getByLabelText("County")).toHaveDisplayValue("Champaign");
    expect(screen.getByText(/available in Illinois, Iowa and Nebraska for now/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get analysis" })).toBeDisabled();
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
