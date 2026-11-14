/** Runtime config from Vite env vars. No secrets belong here: everything is shipped to the browser. */
export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/v1",
  useMocks: import.meta.env.VITE_USE_MOCKS === "1",
} as const;
