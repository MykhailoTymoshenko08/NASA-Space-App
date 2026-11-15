import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { renderRoutes } from "@/shared/lib/test";
import { handlers } from "@/shared/mocks";
import { env } from "@/shared/config";
import { AnalysisPage } from "./AnalysisPage";
import { AnalysisSetupPage } from "./AnalysisSetupPage";

const server = setupServer(...handlers);
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const renderAt = (url: string) =>
  renderRoutes(
    [
      { path: "/analysis", element: <AnalysisSetupPage /> },
      { path: "/analysis/:jobId", element: <AnalysisPage /> },
      { path: "/field", element: <p>Field page</p> },
      { path: "/pick-field", element: <p>Pick page</p> },
    ],
    url,
  );

describe("analysis flow", () => {
  it("sets up, creates the job, polls and shows ranked strategies", async () => {
    const router = renderAt("/analysis?lat=41.5868&lon=-93.625");

    // Crop history is prefilled from the mapped field.
    expect(await screen.findByLabelText("2024")).toHaveValue("Soybeans");
    await userEvent.click(screen.getByRole("button", { name: "Soil health" }));
    expect(screen.getByRole("button", { name: "Soil health" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "5 years" }));
    expect(screen.getByText("Priorities: Soil health. Looking ahead 5 years.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Create analysis/ }));

    expect(await screen.findByRole("heading", { level: 2, name: "Rotation strategies" }, { timeout: 4000 })).toBeInTheDocument();
    expect(router.state.location.pathname).toMatch(/^\/analysis\/[0-9a-f-]{36}$/);
    expect(screen.getByText(/Looking ahead 5 years\. Priorities: Soil health\./)).toBeInTheDocument();

    const best = screen.getByRole("heading", { level: 3, name: "Corn / soybean with winter rye cover" }).closest("article")!;
    expect(within(best).getByText("Best fit")).toBeInTheDocument();
    expect(within(best).getByText("+18 vs your current rotation")).toBeInTheDocument();
    expect(within(best).getByRole("button", { name: "Hide details" })).toHaveAttribute("aria-expanded", "true");

    const current = screen.getByRole("heading", { level: 3, name: /your current rotation/ }).closest("article")!;
    expect(within(current).getByText("Baseline")).toBeInTheDocument();

    expect(screen.getByText(/does not replace a local agronomist/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Soil moisture \(surface\) from/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export to PDF" })).toBeInTheDocument();
  });

  it("shows a failed job with its code and a way to try again", async () => {
    renderAt("/analysis?lat=46.5&lon=-96.8");
    await userEvent.click(await screen.findByRole("button", { name: /Create analysis/ }));
    expect(
      await screen.findByRole("heading", { name: "We could not finish your analysis" }, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(screen.getByText(/UPSTREAM_DATA_UNAVAILABLE/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute("href", expect.stringMatching(/^\/analysis\?/));
  });

  it("reports an unknown job", async () => {
    renderAt("/analysis/00000000-0000-0000-0000-000000000000");
    expect(await screen.findByText(/No analysis with that id/)).toBeInTheDocument();
  });

  it("requires one crop after clearing mapped history, then accepts a corrected history", async () => {
    let requests = 0;
    server.use(http.post(`${env.apiBaseUrl}/analyses`, () => {
      requests++;
      return HttpResponse.json({ error: { code: "RATE_LIMITED", message: "Regression request reached API." } },
        { status: 429 });
    }));
    renderAt("/analysis?lat=41.5868&lon=-93.625");
    await screen.findByLabelText("2024");
    for (const input of screen.getAllByRole("textbox")) await userEvent.clear(input);
    await userEvent.click(screen.getByRole("button", { name: "Create analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter at least one crop");
    expect(requests).toBe(0);
    await userEvent.type(screen.getByLabelText("2024"), "Soybeans");
    await userEvent.click(screen.getByRole("button", { name: "Create analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Regression request reached API.");
    expect(requests).toBe(1);
  });
});
