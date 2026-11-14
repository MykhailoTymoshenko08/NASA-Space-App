import { defineConfig } from "steiger";
import fsd from "@feature-sliced/steiger-plugin";

export default defineConfig([
  ...fsd.configs.recommended,
  // Generated API types are not hand-written code; skip them.
  { ignores: ["**/schema.gen.ts"] },
]);
