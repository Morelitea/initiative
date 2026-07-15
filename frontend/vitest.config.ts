import path from "path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  define: {
    __APP_VERSION__: JSON.stringify("0.0.0-test"),
    __IS_CAPACITOR__: JSON.stringify(false),
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/__tests__/setup.ts"],
    css: false,
    // Tests must be hermetic: a developer's frontend/.env (VITE_API_URL)
    // would otherwise make apiClient requests absolute, bypassing MSW's
    // relative handlers.
    env: { VITE_API_URL: "" },
  },
});
