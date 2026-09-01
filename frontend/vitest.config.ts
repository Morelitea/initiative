import path from "path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  define: {
    __APP_VERSION__: JSON.stringify("0.0.0-test"),
    __IS_CAPACITOR__: JSON.stringify(false),
    // The app serves its own emoji dataset rather than reaching a CDN, and the
    // path is a build-time constant. Without it here the identifier survives
    // into the test bundle and any component that opens the picker throws.
    __EMOJIBASE_URL__: JSON.stringify("/emojibase"),
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
    // Headroom over the 5s default: with every worker transforming the app's
    // heavy import graphs in parallel, userEvent-driven dialog tests can sit
    // queued for seconds on slower dev machines and time out spuriously while
    // passing in isolation. CI finishes comfortably under either ceiling.
    testTimeout: 15_000,
  },
});
