import { api, getAccessToken, type AuthTokens } from "@/shared/api";
import { authApi } from "../api/auth-api";
import { clearSession, getSession, restoreSession, signIn, signOut, signUp } from "./session";

const tokens: AuthTokens = {
  access_token: "test-access-token",
  token_type: "bearer",
  expires_in: 900,
  user: { id: "test-user", email: "farmer@example.com", created_at: "2026-01-01T00:00:00Z" },
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  clearSession();
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => { clearSession(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("finishes startup restoration before accepting a new sign-in", async () => {
  const pending = deferred<AuthTokens>();
  const refresh = vi.spyOn(authApi, "refresh").mockReturnValue(pending.promise);
  const login = vi.spyOn(authApi, "login").mockResolvedValue(tokens);
  const restoring = restoreSession();
  await vi.waitFor(() => expect(refresh).toHaveBeenCalled());
  const signingIn = signIn({ email: "farmer@example.com", password: "password1", remember: true });
  expect(login).not.toHaveBeenCalled();
  pending.reject(new Error("No previous session"));
  await restoring;
  await signingIn;
  expect(getSession()).toMatchObject({ status: "authenticated", user: tokens.user });
});

it("finishes rotation before logging out and clearing the session", async () => {
  vi.spyOn(authApi, "register").mockResolvedValue(tokens);
  await signUp({ email: tokens.user.email, password: "password1" });
  const pending = deferred<AuthTokens>();
  const refresh = vi.spyOn(authApi, "refresh").mockReturnValue(pending.promise);
  const logout = vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
  const restoring = restoreSession();
  await vi.waitFor(() => expect(refresh).toHaveBeenCalled());
  const signingOut = signOut();
  expect(logout).not.toHaveBeenCalled();
  pending.resolve(tokens);
  await restoring;
  await signingOut;
  expect(getSession().status).toBe("anonymous");
  expect(getAccessToken()).toBeNull();
  expect(sessionStorage.getItem("fieldline.tab")).toBeNull();
});

it("does not accept an in-flight refresh after the session is explicitly cleared", async () => {
  const pending = deferred<AuthTokens>();
  const refresh = vi.spyOn(authApi, "refresh").mockReturnValue(pending.promise);
  const restoring = restoreSession();
  await vi.waitFor(() => expect(refresh).toHaveBeenCalled());
  clearSession();
  pending.resolve(tokens);
  await restoring;
  expect(getSession().status).toBe("anonymous");
  expect(getAccessToken()).toBeNull();
});

it("keeps a failed logout visible and retryable instead of pretending it succeeded", async () => {
  vi.spyOn(authApi, "register").mockResolvedValue(tokens);
  await signUp({ email: tokens.user.email, password: "password1" });
  vi.spyOn(authApi, "logout").mockRejectedValue(new Error("Offline"));
  await expect(signOut()).rejects.toThrow("Offline");
  expect(getSession().status).toBe("authenticated");
  expect(getAccessToken()).toBe(tokens.access_token);
});

it("preserves the nonremembered preference across new tabs", async () => {
  localStorage.setItem("fieldline.remember", "0");
  const logout = vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
  const refresh = vi.spyOn(authApi, "refresh");
  await restoreSession();
  await restoreSession();
  expect(logout).not.toHaveBeenCalled();
  expect(refresh).not.toHaveBeenCalled();
  expect(localStorage.getItem("fieldline.remember")).toBe("0");
  expect(getSession().status).toBe("anonymous");
});

it("keeps the original nonremembered tab refreshable after an independent tab starts", async () => {
  let cookieValid = true;
  vi.spyOn(authApi, "login").mockResolvedValue(tokens);
  const logout = vi.spyOn(authApi, "logout").mockImplementation(async () => { cookieValid = false; });
  const refresh = vi.spyOn(authApi, "refresh").mockImplementation(async () => {
    if (!cookieValid) throw new Error("Refresh cookie revoked");
    return tokens;
  });
  await signIn({ email: tokens.user.email, password: "password1", remember: false });

  // Independent tabs share localStorage/cookies but have no original tab's sessionStorage marker.
  sessionStorage.removeItem("fieldline.tab");
  await restoreSession();
  expect(getSession().status).toBe("anonymous");
  expect(getAccessToken()).toBeNull();
  expect(refresh).not.toHaveBeenCalled();

  // The original tab retains its marker and must still restore using the shared refresh cookie.
  sessionStorage.setItem("fieldline.tab", "1");
  await restoreSession();
  expect(logout).not.toHaveBeenCalled();
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(getSession()).toMatchObject({ status: "authenticated", user: tokens.user });
  expect(getAccessToken()).toBe(tokens.access_token);
});

it("clears a revoked session when a protected API rejects its access token", async () => {
  vi.spyOn(authApi, "register").mockResolvedValue(tokens);
  await signUp({ email: tokens.user.email, password: "password1" });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
  await api.GET("/me");
  expect(getSession().status).toBe("anonymous");
  expect(getAccessToken()).toBeNull();
});

it("does not clear the session for a wrong current password", async () => {
  vi.spyOn(authApi, "register").mockResolvedValue(tokens);
  await signUp({ email: tokens.user.email, password: "password1" });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
  await api.POST("/auth/change-password", { body: { current_password: "wrong", new_password: "password2" } });
  expect(getSession().status).toBe("authenticated");
});

it("ignores an old account's rejected request after another account signs in", async () => {
  vi.spyOn(authApi, "register").mockResolvedValue(tokens);
  await signUp({ email: tokens.user.email, password: "password1" });
  const pending = deferred<Response>();
  const fetch = vi.fn().mockReturnValue(pending.promise);
  vi.stubGlobal("fetch", fetch);
  const request = api.GET("/me");
  await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
  vi.spyOn(authApi, "login").mockResolvedValue({ ...tokens, access_token: "another-token" });
  await signIn({ email: tokens.user.email, password: "password1", remember: true });
  pending.resolve(new Response("{}", { status: 401 }));
  await request;
  expect(getSession().status).toBe("authenticated");
  expect(getAccessToken()).toBe("another-token");
});
