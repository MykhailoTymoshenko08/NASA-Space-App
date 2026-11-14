import type { components } from "./schema.gen";

export type ErrorCode = components["schemas"]["ErrorCode"];

/** Friendly English messages per contract error code (one place). */
const FRIENDLY: Record<ErrorCode, string> = {
  UNPARSEABLE_INPUT:
    "We couldn't read that. Paste coordinates like 41.5868, -93.6250 or a Google/Apple Maps link.",
  UNSUPPORTED_LINK: "That link doesn't include a location we can read. Try pasting the coordinates instead.",
  OUTSIDE_COVERAGE: "This tool currently covers the contiguous United States.",
  NOT_FOUND: "We couldn't find that field. Pick it again.",
  RATE_LIMITED: "Too many requests right now. Please wait a moment and try again.",
  UPSTREAM_DATA_UNAVAILABLE: "A data source we rely on is not answering right now. Try again in a few minutes.",
  VALIDATION_ERROR: "Something in that request wasn't valid. Check the location and try again.",
  INTERNAL_ERROR: "Something went wrong on our side. Try again in a moment.",
  UNAUTHORIZED: "Your email or password is not right, or your session ended. Sign in again.",
  EMAIL_TAKEN: "An account with this email already exists. Sign in instead.",
  FIELD_LIMIT_REACHED: "You have saved the most fields allowed. Remove one to save another.",
};

const NETWORK_MESSAGE = "We couldn't reach our server. Check your connection and try again.";

/** Typed error for every failed request. `code` is NETWORK when no HTTP response arrived. */
export class ApiError extends Error {
  readonly code: ErrorCode | "NETWORK";
  readonly status: number | null;
  readonly requestId: string | null;
  readonly details: Record<string, unknown> | null;
  readonly retryAfterSeconds: number | null;
  /** True when `message` came from the backend's error envelope (safe to show, per contract). */
  readonly fromServer: boolean;

  constructor(init: {
    code: ErrorCode | "NETWORK";
    message: string;
    status?: number | null;
    requestId?: string | null;
    details?: Record<string, unknown> | null;
    retryAfterSeconds?: number | null;
    fromServer?: boolean;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.code = init.code;
    this.status = init.status ?? null;
    this.requestId = init.requestId ?? null;
    this.details = init.details ?? null;
    this.retryAfterSeconds = init.retryAfterSeconds ?? null;
    this.fromServer = init.fromServer ?? false;
  }
}

const isErrorCode = (v: unknown): v is ErrorCode => typeof v === "string" && v in FRIENDLY;

/** Build an ApiError from an HTTP response and its (possibly non-JSON) body. */
export function toApiError(response: Response, body: unknown): ApiError {
  const env = (body as { error?: components["schemas"]["ApiError"] } | null)?.error;
  const code: ErrorCode = isErrorCode(env?.code)
    ? env.code
    : response.status === 404
      ? "NOT_FOUND"
      : response.status === 429
        ? "RATE_LIMITED"
        : "INTERNAL_ERROR";
  const retry = Number(response.headers.get("Retry-After"));
  return new ApiError({
    code,
    message: env?.message ?? FRIENDLY[code],
    status: response.status,
    requestId: env?.request_id ?? response.headers.get("X-Request-Id"),
    details: env?.details ?? null,
    retryAfterSeconds: Number.isFinite(retry) && retry > 0 ? retry : null,
    fromServer: typeof env?.message === "string" && env.message.length > 0,
  });
}

export const networkError = (cause: unknown) =>
  Object.assign(new ApiError({ code: "NETWORK", message: NETWORK_MESSAGE }), { cause });

/**
 * What to show the user. The contract says `error.message` is safe to show, so the backend's own
 * message wins; our wording per code is the fallback. Rate limits include the wait time.
 */
export function friendlyMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return FRIENDLY.INTERNAL_ERROR;
  if (error.code === "NETWORK") return NETWORK_MESSAGE;
  if (error.code === "RATE_LIMITED" && error.retryAfterSeconds) {
    return `Too many requests right now. Try again in ${error.retryAfterSeconds} seconds.`;
  }
  if (error.fromServer) return error.message;
  return FRIENDLY[error.code];
}

/** Our own wording for a code, ignoring the server message (for codes the UI words itself). */
export const messageForCode = (code: ErrorCode) => FRIENDLY[code];
