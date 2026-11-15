/** Only same-site paths are allowed as a return target. */
export const safeNext = (next: string | null) =>
  next && next.startsWith("/") && !next.startsWith("//") && !/[\s\\]/.test(next) ? next : null;
