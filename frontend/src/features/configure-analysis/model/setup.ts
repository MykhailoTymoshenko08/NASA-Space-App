import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { createAnalysisJob, DEFAULT_HORIZON } from "@/entities/analysis";
import type { AnalysisRequest, FieldSelection, Priority, SelectionRef } from "@/shared/api";

export type CropRow = { year: number; crop: string };
type CropOverride = NonNullable<NonNullable<NonNullable<AnalysisRequest["options"]>["budget"]>["crop_overrides"]>[number];
/** The farmer's own crop budgets, already parsed; `error` blocks submission. */
export type CropOverrides = { overrides: CropOverride[]; error: string | null };

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
  budget?: NonNullable<AnalysisRequest["options"]>["budget"];
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
      ...(input.budget ? { budget: input.budget } : {}),
    },
  };
}

export function useAnalysisSetup(selection: FieldSelection | null) {
  const [priorities, setPriorities] = useState<Priority[]>([]);
  const [horizon, setHorizon] = useState(DEFAULT_HORIZON);
  const [landRent, setLandRent] = useState("");
  const [coverCost, setCoverCost] = useState("");
  const [crops, setCrops] = useState<CropRow[] | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const mapped = initialCropRows(selection);
  const rows = crops ?? mapped;

  const togglePriority = (p: Priority) =>
    setPriorities((list) => (list.includes(p) ? list.filter((x) => x !== p) : [...list, p]));
  const setCrop = (year: number, crop: string) => {
    setValidationError(null);
    setCrops(rows.map((r) => (r.year === year ? { ...r, crop } : r)));
  };

  const create = useMutation({ mutationFn: createAnalysisJob });

  const submit = (crop?: CropOverrides) => {
    if (!selection) return Promise.reject(new Error("No field"));
    if (crop?.error) {
      setValidationError(crop.error);
      return Promise.reject(new Error(crop.error));
    }
    const ref: SelectionRef = selection.field_id ? { field_id: selection.field_id } : { point: selection.anchor };
    const overrides = crop?.overrides ?? [];
    const budget = landRent !== "" || coverCost !== "" || overrides.length > 0 ? {
      ...(landRent !== "" ? { land_rent_per_acre: Number(landRent) } : {}),
      ...(coverCost !== "" ? { cover_cost_per_acre: Number(coverCost) } : {}),
      ...(overrides.length > 0 ? { crop_overrides: overrides } : {}),
    } : undefined;
    const request = buildAnalysisRequest({ selection: ref, priorities, crops: rows, mapped, horizon, budget });
    if (request.options?.crop_history?.length === 0) {
      const message = "Enter at least one crop before creating an analysis.";
      setValidationError(message);
      return Promise.reject(new Error(message));
    }
    setValidationError(null);
    return create.mutateAsync(request);
  };

  return { priorities, togglePriority, horizon, setHorizon, crops: rows, setCrop, submit, create,
    landRent, setLandRent, coverCost, setCoverCost, validationError };
}

export type AnalysisSetupState = ReturnType<typeof useAnalysisSetup>;
