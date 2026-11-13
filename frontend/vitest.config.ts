import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  root: __dirname,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    root: __dirname,
    environment: "./src/test-env.ts",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    testTimeout: 20000,
  },
});
