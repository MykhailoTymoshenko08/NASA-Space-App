import { defineConfig } from "steiger";
import fsd from "@feature-sliced/steiger-plugin";

export default defineConfig([
  ...fsd.configs.recommended,
  // Generated API types are not hand-written code; skip them.
  { ignores: ["**/schema.gen.ts"] },
  {
    // Off on purpose: several feature and widget slices (pick-by-county, pick-by-location,
    // export-pdf, explore-map, pick-map) have one consumer each. They are kept as slices because
    // each one is a separate user interaction or self-contained block, per the design handoff.
    rules: { "fsd/insignificant-slice": "off" },
  },
]);
