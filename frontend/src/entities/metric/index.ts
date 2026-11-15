export { GLOSSARY, HINTS, readingFor } from "./lib/glossary";
export type { GlossaryTerm, MetricHint } from "./lib/glossary";
export { QUALITY, groupMetrics, isCoarse, presentMetric } from "./lib/present";
export type { MetricGroup, PresentedMetric, QualityTone } from "./lib/present";
export { buildSourceRegistry } from "./lib/sources";
export type { SourceEntry, SourceRegistry } from "./lib/sources";
export {
  Glossary,
  MetricCard,
  MetricGridSkeleton,
  MetricGroups,
  SourcesList,
  SourcesStrip,
  useSourceRegistry,
} from "./ui/MetricCard";
