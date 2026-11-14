import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FieldSelection } from "@/shared/api";
import { savedFieldsApi, type SavedField } from "../api/saved-fields-api";

const key = (userId: string | null) => ["saved-fields", userId] as const;

/** The signed-in user's saved fields. Pass null when signed out (returns nothing). */
export function useSavedFields(userId: string | null) {
  return useQuery({
    queryKey: key(userId),
    queryFn: () => savedFieldsApi.list(userId!),
    enabled: userId !== null,
    staleTime: 0,
  });
}

export function useSavedFieldMutations(userId: string | null) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: key(userId) });
  const save = useMutation({
    mutationFn: (input: { key: string; selection: FieldSelection; bestRotation?: SavedField["bestRotation"] }) =>
      savedFieldsApi.save(userId!, { key: input.key, selection: input.selection, bestRotation: input.bestRotation ?? null }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (fieldKey: string) => savedFieldsApi.remove(userId!, fieldKey),
    onSuccess: invalidate,
  });
  const setBestRotation = useMutation({
    mutationFn: (input: { key: string; best: SavedField["bestRotation"] }) =>
      savedFieldsApi.setBestRotation(userId!, input.key, input.best),
    onSuccess: invalidate,
  });
  return { save, remove, setBestRotation };
}
