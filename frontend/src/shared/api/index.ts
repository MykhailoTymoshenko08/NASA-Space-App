export { api, unwrap } from "./client";
export { ApiError, friendlyMessage } from "./errors";
export type { ErrorCode } from "./errors";
export type { components, paths } from "./schema.gen";

import type { components } from "./schema.gen";
type S = components["schemas"];
export type FieldSelection = S["FieldSelection"];
export type SelectionRef = S["SelectionRef"];
export type Snapshot = S["Snapshot"];
export type Metric = S["Metric"];
export type AnalysisJob = S["AnalysisJob"];
