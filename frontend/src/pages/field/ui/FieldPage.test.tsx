import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { createMemoryRouter, RouterProvider } from "react-router";
import { env } from "@/shared/config";
import { handlers } from "@/shared/mocks";
import { FieldPage } from "./FieldPage";

const server = setupServer(...handlers);
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderAt(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/field", element: <FieldPage /> },
      { path: "/analysis/:jobId", element: <p>Analysis page</p> },
      { path: "/pick-field", element: <p>Pick page</p> },
    ],
    { initialEntries: [url] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

const card = (title: string) => screen.getByRole("heading", { name: title, level: 3 }).closest("article")!;

describe("FieldPage", () => {
  it("shows loading cards, then the field and its base conditions in US units", async () => {
    renderAt("/field?lat=41.5868&lon=-93.625");
    expect(screen.getAllByText("Fetching from our server…")).toHaveLength(4);

    expect(await screen.findByRole("heading", { level: 1, name: /^Field fld_demo/ })).toBeInTheDocument();
    expect(screen.getByText("Polk County, IA")).toBeInTheDocument();
    expect(screen.getByText("About 78 acres")).toBeInTheDocument();
    expect(screen.getByText("41.5868° N, 93.6250° W")).toBeInTheDocument();

    expect(within(card("Humidity")).getByText("68")).toBeInTheDocument();
    expect(within(card("Soil moisture")).getByText("% by volume")).toBeInTheDocument();
    expect(within(card("Temperature")).getByText("°F")).toBeInTheDocument();
    expect(within(card("Temperature")).getByText("57")).toBeInTheDocument();
    expect(within(card("Nitrogen index")).getByText("Estimate")).toBeInTheDocument();

    // Extra metric keys render generically.
    expect(within(card("Rain, last 30 days")).getByText("in")).toBeInTheDocument();
    // Honesty notes.
    expect(screen.getByText(/^Estimated field area/)).toBeInTheDocument();
    expect(within(card("Humidity")).getByText(/Coarse data: a regional average/)).toBeInTheDocument();
  });

  it("shows one card's error state while the others still load fine", async () => {
    renderAt("/field?lat=46.5&lon=-96.8");
    const soil = await screen.findByText(/did not answer\. Your other values are fine\./);
    expect(soil).toBeInTheDocument();
    expect(screen.getByText("No satellite pass over this spot in the last 7 days.")).toBeInTheDocument();
    expect(within(card("Soil moisture")).getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(within(card("Humidity")).getByText("68")).toBeInTheDocument();
  });

  it("explains a point outside coverage and offers to pick again", async () => {
    renderAt("/field?lat=51.5&lon=-0.12");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This tool currently covers the contiguous United States.");
    expect(alert).toHaveTextContent(/Request ID: mock-/);
    expect(within(alert).getByRole("link", { name: "Choose a different field" })).toHaveAttribute("href", "/pick-field");
    expect(screen.getAllByRole("button", { name: "Try again" })).toHaveLength(4);
  });

  it("asks for a location when the URL has none or a bad one", () => {
    renderAt("/field");
    expect(screen.getByRole("alert")).toHaveTextContent("This link doesn't say which field to show.");
  });

  it("rejects out-of-range coordinates without calling the server", () => {
    renderAt("/field?lat=123&lon=-93");
    expect(screen.getByRole("alert")).toHaveTextContent(/isn't valid/);
  });

  it("recovers on Try again", async () => {
    let calls = 0;
    server.use(
      http.post(`${env.apiBaseUrl}/snapshots`, () => {
        calls += 1;
        if (calls === 1) return HttpResponse.json({ error: { code: "INTERNAL_ERROR", message: "boom" } }, { status: 500 });
        return undefined; // fall through to the default mock
      }),
    );
    renderAt("/field?lat=41.5868&lon=-93.625");
    await screen.findByRole("alert");
    await userEvent.click(within(card("Humidity")).getByRole("button", { name: "Try again" }));
    expect(await within(card("Humidity")).findByText("68")).toBeInTheDocument();
  });

  it("starts an analysis and opens its page", async () => {
    const router = renderAt("/field?lat=41.5868&lon=-93.625");
    const button = screen.getByRole("button", { name: "Get analysis" });
    expect(button).toBeDisabled();
    await screen.findByRole("heading", { level: 1, name: /^Field fld_demo/ });
    await userEvent.click(screen.getByRole("button", { name: "Get analysis" }));
    expect(await screen.findByText("Analysis page")).toBeInTheDocument();
    expect(router.state.location.pathname).toMatch(/^\/analysis\/[0-9a-f-]{36}$/);
  });
});
