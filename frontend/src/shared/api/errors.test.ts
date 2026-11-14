import { ApiError, friendlyMessage, networkError, toApiError } from "./errors";

const res = (status: number, headers: Record<string, string> = {}) => new Response(null, { status, headers });

describe("toApiError", () => {
  it("reads the contract error envelope", () => {
    const err = toApiError(res(422), {
      error: { code: "OUTSIDE_COVERAGE", message: "Outside CONUS", request_id: "req-1", details: { field: "point" } },
    });
    expect(err.code).toBe("OUTSIDE_COVERAGE");
    expect(err.requestId).toBe("req-1");
    expect(err.details).toEqual({ field: "point" });
    expect(err.status).toBe(422);
  });

  it("falls back on status code when the body is not an envelope", () => {
    expect(toApiError(res(404), "nope").code).toBe("NOT_FOUND");
    expect(toApiError(res(500), null).code).toBe("INTERNAL_ERROR");
  });

  it("uses X-Request-Id when the body has none", () => {
    expect(toApiError(res(500, { "X-Request-Id": "hdr-9" }), null).requestId).toBe("hdr-9");
  });

  it("reads Retry-After on rate limits", () => {
    const err = toApiError(res(429, { "Retry-After": "12" }), { error: { code: "RATE_LIMITED", message: "slow" } });
    expect(err.retryAfterSeconds).toBe(12);
    expect(friendlyMessage(err)).toBe("Too many requests right now. Try again in 12 seconds.");
  });
});

describe("friendlyMessage", () => {
  it("maps each code to our own wording when the server sent no message", () => {
    const err = new ApiError({ code: "OUTSIDE_COVERAGE", message: "client text" });
    expect(friendlyMessage(err)).toBe("This tool currently covers the contiguous United States.");
  });

  it("shows the server's error.message when the envelope has one", () => {
    const err = toApiError(res(422), { error: { code: "OUTSIDE_COVERAGE", message: "Point is outside CONUS." } });
    expect(friendlyMessage(err)).toBe("Point is outside CONUS.");
  });

  it("explains network failures", () => {
    expect(friendlyMessage(networkError(new TypeError("fetch failed")))).toMatch(/couldn't reach our server/);
  });

  it("never leaks unknown errors", () => {
    expect(friendlyMessage(new Error("stack trace here"))).toBe("Something went wrong on our side. Try again in a moment.");
  });
});
