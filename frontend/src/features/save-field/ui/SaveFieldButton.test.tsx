import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type { SavedFieldDto } from "@/shared/api";
import { env } from "@/shared/config";
import { renderRoutes } from "@/shared/lib/test";
import { DEFAULT_POINT, selectionFor } from "@/shared/mocks";
import { SaveFieldButton } from "./SaveFieldButton";

vi.mock("@/entities/session", () => ({
  useSession: () => ({ status: "authenticated", user: { id: "farmer" } }),
}));

const server = setupServer();
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

it.each([true, false])("blocks saves after list failure and recovers with existing field = %s", async (existing) => {
  const selection = selectionFor(DEFAULT_POINT, "coordinates");
  const saved: SavedFieldDto = {
    id: "saved-field", name: "Home field", field_id: selection.field_id, geometry: selection.geometry,
    centroid: selection.anchor, area_ha: selection.area_ha, state: "IA", crop_history: null,
    info: null, info_fetched_at: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  };
  let reads = 0;
  let creates = 0;
  let deletes = 0;
  server.use(
    http.get(`${env.apiBaseUrl}/me/fields`, () => {
      if (++reads === 1) return HttpResponse.json({ error: { code: "INTERNAL_ERROR", message: "Saved list unavailable." } },
        { status: 503 });
      return HttpResponse.json({ items: existing && deletes === 0 ? [saved] : [], limit: 50 });
    }),
    http.post(`${env.apiBaseUrl}/me/fields`, () => { creates++; return HttpResponse.json(saved, { status: 201 }); }),
    http.delete(`${env.apiBaseUrl}/me/fields/${saved.id}`, () => { deletes++; return new HttpResponse(null, { status: 204 }); }),
  );
  renderRoutes([{ path: "/", element: <SaveFieldButton selection={selection} /> }], "/");
  expect(await screen.findByRole("alert")).toHaveTextContent("Saved list unavailable.");
  expect(screen.getByRole("button", { name: "Save field" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Save field" }));
  expect(creates).toBe(0);
  await userEvent.click(screen.getByRole("button", { name: "Retry saved fields" }));
  const button = await screen.findByRole("button", { name: existing ? "Saved" : "Save field" });
  expect(button).toBeEnabled();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await userEvent.click(button);
  expect(creates).toBe(existing ? 0 : 1);
  expect(deletes).toBe(existing ? 1 : 0);
});
