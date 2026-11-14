import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/shared/api";

/** Don't retry errors the user has to fix (bad input, outside coverage, not found). */
const shouldRetry = (failureCount: number, error: unknown) => {
  if (error instanceof ApiError && error.status !== null && error.status < 500) return false;
  return failureCount < 2;
};

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: shouldRetry, refetchOnWindowFocus: false, staleTime: 5 * 60_000 },
          mutations: { retry: false },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
