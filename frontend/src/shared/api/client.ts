import createClient from "openapi-fetch";
import { env } from "@/shared/config";
import { networkError, toApiError } from "./errors";
import type { paths } from "./schema.gen";

/** Typed client for our backend only. Never call third-party data APIs from the browser. */
export const api = createClient<paths>({ baseUrl: env.apiBaseUrl });

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
    throw networkError(cause);
  }
  if (!result.response.ok || result.data === undefined) {
    throw toApiError(result.response, result.error);
  }
  return result.data;
}
