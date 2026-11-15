/** Runtime config from Vite env vars. No secrets belong here: everything is shipped to the browser. */

/**
 * A relative VITE_API_BASE_URL (`/v1`, used with the dev-server proxy of `npm run dev:remote`) is made
 * absolute against the page origin: MapLibre does not resolve relative tile URLs.
 */
const absolute = (url: string) =>
  url.startsWith("/") && typeof window !== "undefined" ? `${window.location.origin}${url}` : url;

export const env = {
  apiBaseUrl: absolute(import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/v1"),
  useMocks: import.meta.env.VITE_USE_MOCKS === "1",
} as const;
