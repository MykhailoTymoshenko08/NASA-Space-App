import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FieldSelection, SavedFieldUpdate } from "@/shared/api";
import { createBodyFor, savedFieldsApi } from "../api/saved-fields-api";

const key = (userId: string | null) => ["saved-fields", userId] as const;

/** GET /me/fields for the signed-in user. Pass null when signed out (no request). */
export function useSavedFields(userId: string | null) {
  return useQuery({
    queryKey: key(userId),
    queryFn: () => savedFieldsApi.list(),
    enabled: userId !== null,
    staleTime: 30_000,
  });
}

export function useSavedFieldMutations(userId: string | null) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: key(userId) });
  const save = useMutation({
    mutationFn: (selection: FieldSelection) => savedFieldsApi.create(createBodyFor(selection)),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => savedFieldsApi.remove(id),
    onSuccess: invalidate,
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: SavedFieldUpdate }) => savedFieldsApi.update(id, body),
    onSuccess: invalidate,
  });
  const refreshInfo = useMutation({
    mutationFn: (id: string) => savedFieldsApi.refreshInfo(id),
    onSuccess: invalidate,
  });
  return { save, remove, update, refreshInfo };
}
