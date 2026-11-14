import createClient from "openapi-fetch";
import { env } from "@/shared/config";
import { getAccessToken } from "./access-token";
import { networkError, toApiError } from "./errors";
import type { paths } from "./schema.gen";

/** Typed client for our backend only. Never call third-party data APIs from the browser. */
// fetch is looked up per call (not captured once), so test and mock interceptors always apply.
export const api = createClient<paths>({ baseUrl: env.apiBaseUrl, fetch: (request) => globalThis.fetch(request) });

api.use({
  onRequest({ request }) {
    const token = getAccessToken();
    if (token && !request.headers.has("Authorization")) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
});

/** Absolute URL of a backend path, for map tile templates that MapLibre fetches itself. */
export const apiUrl = (path: string) => `${env.apiBaseUrl.replace(/\/$/, "")}${path}`;

type Result<T> = { data?: T; error?: unknown; response: Response };

/**
 * Await an openapi-fetch call and return its data, or throw a typed ApiError.
 * Usage: const snap = await unwrap(api.POST("/snapshots", { body }));
 */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  let result: Result<T>;
  try {
    result = await call;
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw networkError(cause);
  }
  if (!result.response.ok) throw toApiError(result.response, result.error);
  // 204 responses (logout) carry no body; openapi-fetch gives `{}` or undefined.
  return result.data as T;
}
