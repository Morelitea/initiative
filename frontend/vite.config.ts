import path from "path";
import fs from "fs";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import { defineConfig, loadEnv } from "vite";

// Load VITE_* vars from .env files (checks backend/.env and frontend/)
const env = {
  ...loadEnv("production", path.resolve(import.meta.dirname, "../backend"), "VITE_"),
  ...loadEnv("production", process.cwd(), "VITE_"),
};

const devProxyTarget = process.env.VITE_DEV_PROXY_TARGET ?? "http://localhost:8000";

// Read version from VERSION file at project root
const getVersion = () => {
  try {
    const versionPath = path.resolve(import.meta.dirname, "../VERSION");
    const version = fs.readFileSync(versionPath, "utf-8").trim();
    // Append suffix for dev builds (e.g., "-dev-abc1234")
    const suffix = process.env.VITE_VERSION_SUFFIX || "";
    return version + suffix;
  } catch {
    return "0.0.0";
  }
};

const createProxyConfig = (supportsWebSocket = false) => ({
  target: devProxyTarget,
  changeOrigin: true,
  ws: supportsWebSocket,
});

// The emoji picker (frimousse) fetches its dataset at runtime from
// `${emojibaseUrl}/${locale}/{data,messages}.json`, defaulting to a public CDN.
// A self-hosted install may have no internet at all, so the files are served
// from the app itself: copied out of the `emojibase-data` package into
// `/emojibase/...` at build time, and served straight from node_modules in dev.
// Only the locales the app actually ships translations for are copied.
const EMOJI_LOCALES = ["en", "de", "es", "fr"];
const EMOJI_FILES = ["data.json", "messages.json"];
const EMOJI_BASE_PATH = "/emojibase";

const emojibaseSource = (locale: string, file: string) =>
  path.resolve(import.meta.dirname, "node_modules/emojibase-data", locale, file);

const emojibasePlugin = () => ({
  name: "initiative-emojibase",
  // Dev: answer the same URLs the build will, without a copy step.
  configureServer(server: { middlewares: { use: (fn: unknown) => void } }) {
    server.middlewares.use(
      (
        req: { url?: string },
        res: { setHeader: (k: string, v: string) => void; end: (body?: unknown) => void },
        next: () => void
      ) => {
        // Two gates on the only path here that reads a URL: the pattern
        // admits no dots or slashes in the locale, and the locale must then be
        // one this app ships. Anything else falls through to the SPA.
        const match = req.url?.match(
          /^\/emojibase\/([a-z-]+)\/(data|messages)\.json$/
        );
        if (!match) return next();
        const [, locale, name] = match;
        if (!EMOJI_LOCALES.includes(locale)) return next();
        res.setHeader("Content-Type", "application/json");
        res.end(fs.readFileSync(emojibaseSource(locale, `${name}.json`)));
      }
    );
  },
  // Build: emit the files as static assets at their expected paths.
  generateBundle(this: { emitFile: (f: unknown) => void }) {
    for (const locale of EMOJI_LOCALES) {
      for (const file of EMOJI_FILES) {
        this.emitFile({
          type: "asset",
          fileName: `emojibase/${locale}/${file}`,
          source: fs.readFileSync(emojibaseSource(locale, file), "utf-8"),
        });
      }
    }
  },
});

// Use relative paths for Capacitor builds (mobile apps load from file:// or local server)
const isCapacitorBuild = process.env.CAPACITOR_BUILD === "true";

export default defineConfig({
  base: isCapacitorBuild ? "" : "/",
  define: {
    __APP_VERSION__: JSON.stringify(getVersion()),
    __IS_CAPACITOR__: JSON.stringify(isCapacitorBuild),
    // Absolute, on native too: the Capacitor WebView serves index.html from
    // its origin root, so a relative URL would resolve against whatever route
    // the app happens to be on when the picker first opens.
    __EMOJIBASE_URL__: JSON.stringify(EMOJI_BASE_PATH),
  },
  plugins: [
    // A route's tests sit beside it and export no Route of their own, so the
    // generator skips them rather than treating each as a missing route.
    tanstackRouter({ routeFileIgnorePattern: "\\.test\\.[jt]sx?$" }),
    react(),
    tailwindcss(),
    emojibasePlugin(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  worker: {
    // Worker bundles land in their own directory so a served response can be
    // matched by path. The backend keys the widget sandbox's policy off
    // `assets/workers/sandbox.worker-` — see `_WIDGET_SANDBOX_ASSET` in
    // backend/app/main.py, which is pinned by tests on both sides.
    rolldownOptions: {
      output: {
        entryFileNames: "assets/workers/[name]-[hash].js",
        chunkFileNames: "assets/workers/[name]-[hash].js",
      },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: "lucide-react",
              test: /\/lucide-react\//,
            },
          ],
        },
      },
    },
  },
  server: {
    // scripts/dev-ports.sh sets this per checkout so linked worktrees can run
    // side by side; a bare `pnpm dev` keeps the default.
    port: Number(process.env.VITE_DEV_PORT ?? 5173),
    strictPort: true,
    proxy: {
      // WebSocket endpoint needs explicit configuration
      "/api/v1/collaboration": {
        target: devProxyTarget,
        changeOrigin: true,
        ws: true,
        // Log proxy events for debugging
        configure: (proxy) => {
          proxy.on("error", (err) => {
            console.log("Proxy error:", err);
          });
          proxy.on("proxyReqWs", (proxyReq, req) => {
            console.log("Proxying WebSocket:", req.url);
          });
        },
      },
      "/api": createProxyConfig(true),
      "/uploads": createProxyConfig(),
    },
  },
});
