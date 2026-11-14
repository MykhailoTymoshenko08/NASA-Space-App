import { useSyncExternalStore } from "react";
import { setAccessToken, type AuthTokens, type User } from "@/shared/api";
import { authApi } from "../api/auth-api";

/**
 * Session state for the whole app.
 * - The access token lives in memory only (shared/api), never in storage.
 * - The refresh token is an httpOnly cookie; on start we call /auth/refresh to restore the session.
 * - "Keep me signed in" off: the session ends with the browser tab (we sign out on the next start).
 */
export type SessionState =
  | { status: "unknown"; user: null }
  | { status: "anonymous"; user: null }
  | { status: "authenticated"; user: User };

let state: SessionState = { status: "unknown", user: null };
const listeners = new Set<() => void>();
let refreshTimer: ReturnType<typeof setTimeout> | null = null;

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
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = null;
  setAccessToken(null);
  setState({ status: "anonymous", user: null });
}

/** Password updates revoke this session along with every other session for the account. */
export const clearSession = () => clear();

export async function changePassword(currentPassword: string, newPassword: string) {
  await authApi.changePassword(currentPassword, newPassword);
  clear();
}

async function refreshSession(): Promise<boolean> {
  try {
    accept(await authApi.refresh());
    return true;
  } catch {
    clear();
    return false;
  }
}

/** Call once at app start. Restores a session from the refresh cookie, if any. */
export async function restoreSession() {
  const remember = storage.get(local(), REMEMBER_KEY) !== "0";
  const sameTab = storage.get(tab(), TAB_KEY) === "1";
  if (!remember && !sameTab) {
    // The user asked not to stay signed in and this is a new browser session.
    storage.set(local(), REMEMBER_KEY, null);
    await authApi.logout().catch(() => undefined);
    clear();
    return;
  }
  await refreshSession();
}

function rememberChoice(remember: boolean) {
  storage.set(local(), REMEMBER_KEY, remember ? null : "0");
  storage.set(tab(), TAB_KEY, "1");
}

export async function signIn(input: { email: string; password: string; remember: boolean }) {
  const tokens = await authApi.login(input.email.trim(), input.password);
  rememberChoice(input.remember);
  accept(tokens);
  return tokens.user;
}

export async function signUp(input: { email: string; password: string }) {
  const tokens = await authApi.register(input.email.trim(), input.password);
  rememberChoice(true);
  accept(tokens);
  return tokens.user;
}

export async function signOut() {
  try {
    await authApi.logout();
  } finally {
    storage.set(local(), REMEMBER_KEY, null);
    clear();
  }
}
