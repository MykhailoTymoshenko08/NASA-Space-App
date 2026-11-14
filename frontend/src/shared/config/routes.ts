/** Every route path in one place. */
export const ROUTES = {
  home: "/",
  pickField: "/pick-field",
  field: "/field",
  analysis: "/analysis/:jobId",
  signIn: "/sign-in",
} as const;

export const analysisPath = (jobId: string) => `/analysis/${encodeURIComponent(jobId)}`;
