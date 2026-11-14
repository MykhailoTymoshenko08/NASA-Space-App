import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { createAnalysisJob, DEFAULT_HORIZON } from "@/entities/analysis";
import type { AnalysisRequest, FieldSelection, Priority, SelectionRef } from "@/shared/api";

export type CropRow = { year: number; crop: string };

/** Mapped history from the field, or the last three years empty when nothing is mapped. */
export function initialCropRows(selection: FieldSelection | null, now = new Date()): CropRow[] {
  const mapped = selection?.crop_history ?? [];
  if (mapped.length > 0) return mapped.map((c) => ({ year: c.year, crop: c.crop }));
  const last = now.getUTCFullYear() - 1;
  return [last, last - 1, last - 2].map((year) => ({ year, crop: "" }));
}

/** Build the request. Crop history is sent only when the farmer changed it (it replaces the mapped one). */
export function buildAnalysisRequest(input: {
  selection: SelectionRef;
  priorities: readonly Priority[];
  crops: readonly CropRow[];
  mapped: readonly CropRow[];
  horizon: number;
}): AnalysisRequest {
  const cleaned = input.crops
    .map((c) => ({ year: c.year, crop: c.crop.trim() }))
    .filter((c) => c.crop.length > 0)
    .slice(0, 10);
  const mapped = input.mapped.filter((c) => c.crop.trim().length > 0);
  const changed = JSON.stringify(cleaned) !== JSON.stringify(mapped);
  return {
    selection: input.selection,
    options: {
      priorities: [...input.priorities],
      horizon_years: input.horizon,
      ...(changed ? { crop_history: cleaned } : {}),
    },
  };
}

export function useAnalysisSetup(selection: FieldSelection | null) {
  const [priorities, setPriorities] = useState<Priority[]>([]);
  const [horizon, setHorizon] = useState(DEFAULT_HORIZON);
  const [crops, setCrops] = useState<CropRow[] | null>(null);
  const mapped = initialCropRows(selection);
  const rows = crops ?? mapped;

  const togglePriority = (p: Priority) =>
    setPriorities((list) => (list.includes(p) ? list.filter((x) => x !== p) : [...list, p]));
  const setCrop = (year: number, crop: string) => setCrops(rows.map((r) => (r.year === year ? { ...r, crop } : r)));

  const create = useMutation({ mutationFn: createAnalysisJob });

  const submit = () => {
    if (!selection) return Promise.reject(new Error("No field"));
    const ref: SelectionRef = selection.field_id ? { field_id: selection.field_id } : { point: selection.anchor };
    return create.mutateAsync(buildAnalysisRequest({ selection: ref, priorities, crops: rows, mapped, horizon }));
  };

  return { priorities, togglePriority, horizon, setHorizon, crops: rows, setCrop, submit, create };
}

export type AnalysisSetupState = ReturnType<typeof useAnalysisSetup>;
