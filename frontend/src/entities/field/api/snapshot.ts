import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type SelectionRef } from "@/shared/api";

export const snapshotQueryKey = (ref: SelectionRef) => ["snapshot", ref] as const;

/** POST /snapshots: the field plus its base metrics, in one call to our backend. */
export const fetchSnapshot = (ref: SelectionRef, signal?: AbortSignal) =>
  unwrap(api.POST("/snapshots", { body: { selection: ref }, signal }));

export function useFieldSnapshot(ref: SelectionRef | null) {
  return useQuery({
    queryKey: ref ? snapshotQueryKey(ref) : ["snapshot", "none"],
    queryFn: ({ signal }) => fetchSnapshot(ref!, signal),
    enabled: ref !== null,
  });
}
