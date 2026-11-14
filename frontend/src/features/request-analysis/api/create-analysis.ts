import { useMutation } from "@tanstack/react-query";
import { api, unwrap, type SelectionRef } from "@/shared/api";

/** POST /analyses: starts the async job and returns it (202). */
export function useCreateAnalysis() {
  return useMutation({
    mutationFn: (selection: SelectionRef) => unwrap(api.POST("/analyses", { body: { selection } })),
  });
}
