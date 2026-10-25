import { defineConfig } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";

export default defineConfig([
  {
    ignores: [".next/**", "node_modules/**", "coverage/**", "next-env.d.ts"],
  },
  ...nextVitals,
  {
    rules: {
      // The dashboard loads data on mount and synchronously resets its
      // loading/error state inside the effect. That is an established pattern
      // here; migrating every page to a suspense/query boundary is a separate
      // refactor. Keep the remaining React Compiler rules enabled.
      "react-hooks/set-state-in-effect": "off",
    },
  },
]);
