import { useMemo } from "react";
import type { MapSavedShape } from "@/shared/ui/map";
import { useSavedFields } from "./saved-fields";

/** Saved fields of `userId` as named map shapes. Empty when signed out (null) or still loading. */
export function useSavedFieldShapes(userId: string | null): readonly MapSavedShape[] {
  const saved = useSavedFields(userId);
  return useMemo(
    () => (saved.data?.items ?? []).map((f): MapSavedShape => ({ id: f.id, name: f.name, geometry: f.geometry })),
    [saved.data],
  );
}
