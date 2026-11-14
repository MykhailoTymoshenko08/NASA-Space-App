import type { DatasetRef, Strategy } from "@/shared/api";

/** Contract: strategies come sorted by score. We sort again defensively (stable, descending). */
export const sortStrategies = (list: readonly Strategy[]) => [...list].sort((a, b) => b.score - a.score);

export const rankLabel = (index: number) => (index === 0 ? "Best fit" : `Option ${index + 1}`);

/** "+18 vs your current rotation", or "Baseline" for the current one. */
export function deltaText(strategy: Strategy, baselineScore: number | null): string {
  if (strategy.is_current) return "Baseline";
  if (baselineScore === null) return "";
  const d = Math.round(strategy.score - baselineScore);
  return `${d >= 0 ? "+" : ""}${d} vs your current rotation`;
}

export const confidenceText = (c: Strategy["confidence"]) => `Confidence: ${c.charAt(0).toUpperCase()}${c.slice(1)}`;

export const datasetSource = (d: DatasetRef) => `${d.dataset}, ${d.provider}`;

