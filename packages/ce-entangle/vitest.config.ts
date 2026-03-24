import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts"],
      exclude: ["src/**/*.test.ts", "src/index.ts", "src/types.ts"],
      thresholds: { statements: 80, branches: 70, functions: 75, lines: 80 },
    },
  },
  resolve: {
    alias: {
      "@context-engineering/core": path.resolve(__dirname, "../ce-core/src"),
      "@context-engineering/entangle": path.resolve(__dirname, "./src"),
    },
  },
});
