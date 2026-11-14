import { defineConfig } from "steiger";
import fsd from "@feature-sliced/steiger-plugin";

export default defineConfig([
  ...fsd.configs.recommended,
  // Generated API types are not hand-written code; skip them.
  { ignores: ["**/schema.gen.ts"] },
  {
    // Off on purpose: entities/field, entities/metric, features/request-analysis and
    // widgets/base-conditions have one consumer today, but the pick-field, analysis and
    // landing-map pages (next milestones) reuse them. Re-enable once those pages exist.
    rules: { "fsd/insignificant-slice": "off" },
  },
]);
