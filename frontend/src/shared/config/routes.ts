/** Every route path in one place. */
export const ROUTES = {
  home: "/",
  pickField: "/pick-field",
  field: "/field",
  /** Analysis setup for the field in the query string (?field_id=.. or ?lat=..&lon=..). */
  analysisSetup: "/analysis",
  /** One analysis job: running, result or failed. Keeps the field in the query string. */
  analysis: "/analysis/:jobId",
  signIn: "/sign-in",
  signUp: "/sign-up",
  resetPassword: "/reset-password",
  /** Signed-in password change (POST /auth/change-password). */
  changePassword: "/account/password",
  myFields: "/my-fields",
  /** Signed-in county screening (POST /comparisons/area). */
  areaRanking: "/rank-fields",
  /** Public crop model validation report (numbers from ml/models/crop_model/metrics.json). */
  modelMetrics: "/model",
} as const;

/** `search` is a query string from `buildFieldSearch` ("?field_id=.."), or empty. */
export const analysisPath = (jobId: string, search = "") => `/analysis/${encodeURIComponent(jobId)}${search}`;
export const analysisSetupPath = (search: string) => `${ROUTES.analysisSetup}${search}`;
export const fieldPath = (search: string) => `${ROUTES.field}${search}`;
