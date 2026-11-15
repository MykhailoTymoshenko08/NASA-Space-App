import { useSyncExternalStore } from "react";
import { api, getAccessToken, setAccessToken, type AuthTokens, type User } from "@/shared/api";
import { authApi } from "../api/auth-api";

/**
 * Session state for the whole app.
 * - The access token lives in memory only (shared/api), never in storage.
 * - The refresh token is an httpOnly cookie; on start we call /auth/refresh to restore the session.
 * - "Keep me signed in" off: only the tab that signed in restores its session after a reload.
 */
export type SessionState =
  | { status: "unknown"; user: null }
  | { status: "anonymous"; user: null }
  | { status: "authenticated"; user: User };

let state: SessionState = { status: "unknown", user: null };
const listeners = new Set<() => void>();
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let revision = 0;
let authQueue: Promise<unknown> = Promise.resolve();

// Refresh cookies rotate once. Serialize mutations within this tab and across tabs when supported.
function withAuthLock<T>(operation: () => Promise<T>): Promise<T> {
  const run = () =>
    typeof navigator !== "undefined" && navigator.locks
      ? navigator.locks.request("fieldline.auth", operation)
      : operation();
  const result = authQueue.then(run, run);
  authQueue = result.catch(() => undefined);
  return result;
}

function setState(next: SessionState) {
  state = next;
  for (const l of listeners) l();
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
const getSnapshot = () => state;

export const useSession = () => useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
export const getSession = () => state;

// "Keep me signed in". localStorage holds only this preference; sessionStorage marks a live tab.
const REMEMBER_KEY = "fieldline.remember";
const TAB_KEY = "fieldline.tab";
const storage = {
  get: (s: Storage | undefined, k: string) => {
    try {
      return s?.getItem(k) ?? null;
    } catch {
      return null;
    }
  },
  set: (s: Storage | undefined, k: string, v: string | null) => {
    try {
      if (v === null) s?.removeItem(k);
      else s?.setItem(k, v);
    } catch {
      /* storage blocked: the preference is just not kept */
    }
  },
};
const local = () => (typeof localStorage === "undefined" ? undefined : localStorage);
const tab = () => (typeof sessionStorage === "undefined" ? undefined : sessionStorage);

function accept(tokens: AuthTokens) {
  setAccessToken(tokens.access_token);
  setState({ status: "authenticated", user: tokens.user });
  scheduleRefresh(tokens.expires_in);
}

function scheduleRefresh(expiresInS: number) {
  if (refreshTimer) clearTimeout(refreshTimer);
  // Refresh a minute before expiry (never sooner than 10 s from now).
  const ms = Math.max(10, expiresInS - 60) * 1000;
  refreshTimer = setTimeout(() => void refreshSession(), ms);
}

function clear() {
  revision++;
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = null;
  setAccessToken(null);
  setState({ status: "anonymous", user: null });
}

/** Password updates revoke this session along with every other session for the account. */
export const clearSession = () => clear();

export async function changePassword(currentPassword: string, newPassword: string) {
  await withAuthLock(async () => {
    await authApi.changePassword(currentPassword, newPassword);
    clear();
  });
}

async function refreshSession(): Promise<boolean> {
  return withAuthLock(async () => {
    const started = revision;
    try {
      const tokens = await authApi.refresh();
      if (started !== revision) return false;
      accept(tokens);
      return true;
    } catch {
      if (started === revision) clear();
      return false;
    }
  });
}

// A revoked token must not leave protected UI looking signed in. Ignore auth-form errors and
// responses belonging to an older token, which may arrive after a different account signs in.
api.use({
  onResponse({ request, response }) {
    const token = getAccessToken();
    if (response.status === 401 && token && !new URL(request.url).pathname.includes("/auth/") &&
        request.headers.get("Authorization") === `Bearer ${token}`) clear();
    return response;
  },
});

/** Call once at app start. Restores a session from the refresh cookie, if any. */
export async function restoreSession() {
  const remember = storage.get(local(), REMEMBER_KEY) !== "0";
  const sameTab = storage.get(tab(), TAB_KEY) === "1";
  if (!remember && !sameTab) {
    // A new tab stays anonymous. The refresh cookie is shared with the original tab: do not revoke it.
    await withAuthLock(async () => {
      clear();
    });
    return;
  }
  await refreshSession();
}

function rememberChoice(remember: boolean) {
  storage.set(local(), REMEMBER_KEY, remember ? null : "0");
  storage.set(tab(), TAB_KEY, "1");
}

export async function signIn(input: { email: string; password: string; remember: boolean }) {
  return withAuthLock(async () => {
    const tokens = await authApi.login(input.email.trim(), input.password);
    rememberChoice(input.remember);
    accept(tokens);
    return tokens.user;
  });
}

export async function signUp(input: { email: string; password: string }) {
  return withAuthLock(async () => {
    const tokens = await authApi.register(input.email.trim(), input.password);
    rememberChoice(true);
    accept(tokens);
    return tokens.user;
  });
}

export async function signOut() {
  await withAuthLock(async () => {
    await authApi.logout();
    storage.set(local(), REMEMBER_KEY, null);
    storage.set(tab(), TAB_KEY, null);
    clear();
  });
}
