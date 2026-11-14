import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type SelectionRef, type SelectionSource } from "@/shared/api";
import type { LatLon } from "@/shared/lib";

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

/** GET /fields/{field_id}: a field clicked on the map. */
export const fetchField = (fieldId: string, signal?: AbortSignal) =>
  unwrap(api.GET("/fields/{field_id}", { params: { path: { field_id: fieldId } }, signal }));

export function useField(fieldId: string | null) {
  return useQuery({
    queryKey: ["field", fieldId],
    queryFn: ({ signal }) => fetchField(fieldId!, signal),
    enabled: fieldId !== null,
  });
}

/** POST /fields/resolve: snap a map click to the nearest field, or a buffered circle. */
export const resolveFieldAt = (point: LatLon, source: SelectionSource, signal?: AbortSignal) =>
  unwrap(api.POST("/fields/resolve", { body: { point, source }, signal }));
