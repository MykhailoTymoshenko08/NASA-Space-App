import { setupServer } from "msw/node";
import { createBodyFor, matchesSelection, savedFieldsApi } from "@/entities/saved-field";
import { signOut, signUp } from "@/entities/session";
import { api, ApiError, unwrap } from "@/shared/api";
import { handlers } from "@/shared/mocks";

const server = setupServer(...handlers);
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => localStorage.clear());

const resolve = (lat: number, lon: number) => unwrap(api.POST("/fields/resolve", { body: { point: { lat, lon } } }));

describe("saved fields (GET/POST/DELETE /me/fields)", () => {
  it("needs a signed-in user", async () => {
    await signOut();
    await expect(savedFieldsApi.list()).rejects.toMatchObject({ code: "UNAUTHORIZED" });
  });

  it("saves a mapped field with its polygon and id, lists it, then deletes it", async () => {
    await signUp({ email: "saver@example.com", password: "corn2026" });
    const sel = await resolve(41.5868, -93.625);

    const body = createBodyFor(sel);
    expect(body).toMatchObject({ name: "Polk, IA", field_id: sel.field_id, geometry: { type: "Polygon" } });
    expect(body.crop_history?.[0]).toEqual({ year: 2025, crop: "Corn" });

    const saved = await savedFieldsApi.create(body);
    expect(saved).toMatchObject({ name: "Polk, IA", state: "IA", field_id: sel.field_id });
    expect(matchesSelection(saved, sel)).toBe(true);

    const list = await savedFieldsApi.list();
    expect(list.items.map((f) => f.id)).toEqual([saved.id]);
    expect(list.limit).toBe(50);

    await savedFieldsApi.remove(saved.id);
    expect((await savedFieldsApi.list()).items).toEqual([]);
    await signOut();
  });

  it("saves a buffered circle as its point and refuses places outside IA, IL and NE", async () => {
    await signUp({ email: "points@example.com", password: "soybean1" });
    const outside = await resolve(39.7392, -104.9903);
    const body = createBodyFor(outside);
    expect(body).toMatchObject({ field_id: null, geometry: { type: "Point", coordinates: [-104.9903, 39.7392] } });
    const err = await savedFieldsApi.create(body).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("OUTSIDE_COVERAGE");
    await signOut();
  });
});
