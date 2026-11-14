import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import { env } from "@/shared/config";
import { QueryProvider } from "./query/QueryProvider";
import { router } from "./router/router";
import "@/shared/ui/theme";
import "./styles/global.css";

async function start() {
  if (env.useMocks) {
    // Loaded only in mock mode, so MSW never ships in a real build path.
    const { startMockWorker } = await import("@/shared/mocks");
    await startMockWorker();
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <QueryProvider>
        <RouterProvider router={router} />
      </QueryProvider>
    </StrictMode>,
  );
}

void start();
