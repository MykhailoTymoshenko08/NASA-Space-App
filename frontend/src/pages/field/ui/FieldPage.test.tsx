import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { env } from "@/shared/config";
import { renderRoutes } from "@/shared/lib/test";
import { handlers } from "@/shared/mocks";
import { FieldPage } from "./FieldPage";

const server = setupServer(...handlers);
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const renderAt = (url: string) =>
  renderRoutes(
    [
      { path: "/field", element: <FieldPage /> },
      { path: "/analysis", element: <p>Setup page</p> },
      { path: "/pick-field", element: <p>Pick page</p> },
    ],
    url,
  );

const card = (label: string) => screen.getByRole("heading", { name: label, level: 3 }).closest("article")!;

describe("FieldPage", () => {
  it("loads, then shows the field and metrics grouped by category in US units", async () => {
    renderAt("/field?lat=41.5868&lon=-93.625");
    expect(screen.getByText("Reading NASA data for this field")).toBeInTheDocument();

    expect(await screen.findByText("80 acres (32.4 ha)")).toBeInTheDocument();
    expect(screen.getByText("Estimated field area in Polk County, IA.")).toBeInTheDocument();
    expect(screen.getByText("41.5868° N, 93.6250° W")).toBeInTheDocument();
    expect(screen.getByText("2024 Soybeans")).toBeInTheDocument();
    expect(screen.getByText(/snapped from your point to the nearest outline/)).toBeInTheDocument();

    for (const group of ["Moisture", "Air", "Temperature", "Rain", "Soil", "Terrain", "Plants"]) {
      expect(screen.getByRole("heading", { level: 2, name: group })).toBeInTheDocument();
    }

    const soil = card("Soil moisture (surface)");
    expect(within(soil).getByText("0.27")).toBeInTheDocument();
    expect(within(soil).getByText("m³/m³")).toBeInTheDocument();
    expect(within(soil).getByText("Measured")).toBeInTheDocument();
    const chip = within(soil).getByRole("link", { name: "Source 1: SMAP L3 Enhanced Soil Moisture, NASA" });
    expect(chip).toHaveTextContent("[1] SMAP L3");
    expect(within(soil).getByText(/Wider than this field/)).toBeInTheDocument();

    expect(within(card("Air temperature (30-day mean)")).getByText("57")).toBeInTheDocument();
    expect(within(card("Soil nitrogen (total)")).getByText("Estimate")).toBeInTheDocument();
    const ndvi = card("Plant greenness (NDVI)");
    expect(within(ndvi).getAllByText("Not available")).toHaveLength(2);
    expect(within(ndvi).getByText("No cloud-free satellite pass in the last 14 days.")).toBeInTheDocument();
  });

  it("numbers each source, lists them with a glossary, and opens the NDVI hint", async () => {
    renderAt("/field?lat=41.5868&lon=-93.625");
    await screen.findByText("80 acres (32.4 ha)");

    expect(screen.getByText("Where this data comes from", { selector: "span" })).toBeInTheDocument();
    const sources = screen.getByRole("region", { name: "Where this data comes from" });
    const items = within(sources).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("[1]");
    expect(items[0]).toHaveTextContent("SMAP L3 Enhanced Soil Moisture");
    expect(items[0]).toHaveTextContent(/Used for: Soil moisture \(surface\)/);
    const chip = within(card("Soil moisture (surface)")).getByRole("link", { name: /^Source 1:/ });
    expect(chip).toHaveAttribute("href", `#${items[0]!.id}`);
    expect(screen.getByRole("link", { name: `All ${items.length} sources` })).toHaveAttribute("href", "#sources");

    expect(screen.getByRole("region", { name: "Glossary" })).toHaveTextContent("NDVI (plant greenness)");

    // Sources and Glossary start closed; a link into them opens the box first.
    const sourcesBox = sources.querySelector("details")!;
    const glossaryBox = screen.getByRole("region", { name: "Glossary" }).querySelector("details")!;
    expect(sourcesBox.open).toBe(false);
    expect(glossaryBox.open).toBe(false);
    await userEvent.click(screen.getByRole("link", { name: "Glossary" }));
    expect(glossaryBox.open).toBe(true);
    await userEvent.click(chip);
    expect(sourcesBox.open).toBe(true);

    const hintBtn = within(card("Plant greenness (NDVI)")).getByRole("button", { name: "What is Plant greenness (NDVI)?" });
    expect(hintBtn).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(hintBtn);
    expect(hintBtn).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("note")).toHaveTextContent(/How to read it/);
    expect(within(screen.getByRole("note")).getByRole("link", { name: "See it in the glossary" })).toHaveAttribute(
      "href",
      "#gl-ndvi",
    );
  });

  it("shows Not available with the reason when a source has no value", async () => {
    renderAt("/field?lat=46.5&lon=-96.8");
    const soil = await screen.findByRole("heading", { name: "Soil moisture (surface)", level: 3 });
    expect(within(soil.closest("article")!).getByText(/No satellite pass/)).toBeInTheDocument();
  });

  it("uses a circle outside the supported states", async () => {
    renderAt("/field?lat=39.7392&lon=-104.9903");
    expect(await screen.findByText(/No field outline here, so we use a circle of 300 m \(984 ft\)/)).toBeInTheDocument();
    expect(screen.getByText("Circle around your point")).toBeInTheDocument();
  });

  it("shows the server error with its code, and retries", async () => {
    renderAt("/field?lat=10&lon=10");
    expect(await screen.findByRole("heading", { name: "We could not get conditions for this point" })).toBeInTheDocument();
    expect(screen.getByText("That point is outside the contiguous US.")).toBeInTheDocument();
    expect(screen.getByText(/OUTSIDE_COVERAGE/)).toBeInTheDocument();

    server.use(
      http.post(`${env.apiBaseUrl}/snapshots`, () =>
        HttpResponse.json({ error: { code: "INTERNAL_ERROR", message: "Still broken." } }, { status: 500 }),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Still broken.")).toBeInTheDocument();
  });

  it("links Get analysis to the setup page for this field", async () => {
    const router = renderAt("/field?lat=41.5868&lon=-93.625");
    await screen.findByText("80 acres (32.4 ha)");
    await userEvent.click(screen.getByRole("link", { name: /Get analysis/ }));
    expect(router.state.location.pathname).toBe("/analysis");
    expect(router.state.location.search).toMatch(/^\?field_id=csb2025_demo/);
  });

  it("explains a missing or broken location", () => {
    renderAt("/field?lat=abc&lon=1");
    expect(screen.getByRole("alert")).toHaveTextContent(/isn't valid/);
  });
});
