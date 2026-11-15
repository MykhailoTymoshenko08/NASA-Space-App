/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  // VITE_API_PROXY_TARGET (e.g. `npm run dev:remote` with .env.remote): the dev server forwards /v1 to that
  // backend, so the browser sees one origin and the auth cookie stays first-party.
  const proxyTarget = loadEnv(mode, process.cwd(), "").VITE_API_PROXY_TARGET;
  return {
    plugins: [react()],
    server: proxyTarget
      ? {
          proxy: {
            "/v1": { target: proxyTarget, changeOrigin: true, secure: true },
          },
        }
      : undefined,
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/shared/lib/test/setup.ts"],
      css: false,
      // Page tests walk whole flows (setup, create, poll); allow for slow CI machines.
      testTimeout: 15_000,
    },
  };
});
