import react from "@vitejs/plugin-react";
import path from "path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirror tsconfig's "@/..." → "src/..." alias.
    alias: { "@": path.resolve(__dirname, "src") },
  },
  test: {
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    // Logic and smoke tests want plain node; component tests declare
    // `@vitest-environment jsdom` in their own docblock. Vitest 4 dropped
    // environmentMatchGlobs, and a per-file pragma is clearer anyway than a
    // glob in a config nobody reads.
    environment: "node",
  },
});
