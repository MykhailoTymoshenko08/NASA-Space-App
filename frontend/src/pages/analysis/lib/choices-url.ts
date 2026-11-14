import { PRIORITIES } from "@/entities/analysis";
import type { Priority } from "@/shared/api";

/** Priorities and horizon ride along in the job URL (?p=..&h=..) so the result can describe them after a refresh. */
export function choicesSearch(priorities: readonly Priority[], horizon: number): string {
  const p = new URLSearchParams();
  if (priorities.length) p.set("p", priorities.join(","));
  p.set("h", String(horizon));
  return p.toString();
}

export function readChoices(params: URLSearchParams): { priorities: Priority[] | null; horizon: number | null } {
  const h = Number(params.get("h"));
  const raw = params.get("p");
  const known = new Set<string>(PRIORITIES);
  return {
    priorities: params.has("h") ? (raw ? raw.split(",").filter((x): x is Priority => known.has(x)) : []) : null,
    horizon: Number.isInteger(h) && h >= 1 && h <= 5 ? h : null,
  };
}

/** Join a field query string ("?field_id=..") with extra params. */
export const withParams = (fieldSearch: string, extra: string) =>
  extra ? `${fieldSearch}${fieldSearch.includes("?") ? "&" : "?"}${extra}` : fieldSearch;
