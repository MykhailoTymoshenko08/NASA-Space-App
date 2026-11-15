import { api, unwrap, type components } from "@/shared/api";

export type FieldComparison = components["schemas"]["FieldComparison"];
export type ComparedField = components["schemas"]["ComparedField"];
export type ComparisonRow = components["schemas"]["ComparisonRow"];
export type ComparisonCell = components["schemas"]["ComparisonCell"];
export type ComparisonPlan = components["schemas"]["ComparisonPlan"];
export type SavedFieldComparisonRequest = components["schemas"]["SavedFieldComparisonRequest"];

/** Compare saved fields using the server's budgets, data quality and ranking rules. */
export const fetchFieldComparison = (body: SavedFieldComparisonRequest, signal?: AbortSignal) =>
  unwrap(api.POST("/comparisons/saved-fields", { body, signal }));
