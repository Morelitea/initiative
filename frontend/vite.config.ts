import path from "path";
import fs from "fs";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import { defineConfig } from "vite";

const devProxyTarget = process.env.VITE_DEV_PROXY_TARGET ?? "http://localhost:8000";

// Read version from VERSION file at project root
const getVersion = () => {
  try {
    const versionPath = path.resolve(__dirname, "../VERSION");
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

// Use relative paths for Capacitor builds (mobile apps load from file:// or local server)
const isCapacitorBuild = process.env.CAPACITOR_BUILD === "true";

export default defineConfig({
  base: isCapacitorBuild ? "" : "/",
  define: {
    __APP_VERSION__: JSON.stringify(getVersion()),
    __IS_CAPACITOR__: JSON.stringify(isCapacitorBuild),
  },
  plugins: [tanstackRouter(), react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
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
