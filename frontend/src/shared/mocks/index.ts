import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";

/** Start MSW in the browser. Only imported when VITE_USE_MOCKS=1. */
export async function startMockWorker() {
  await setupWorker(...handlers).start({ quiet: true });
}
