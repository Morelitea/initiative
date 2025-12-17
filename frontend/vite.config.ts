import path from "path";
import fs from "fs";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const devProxyTarget = process.env.VITE_DEV_PROXY_TARGET ?? "http://localhost:8000";

// Read version from VERSION file at project root
const getVersion = () => {
  try {
    const versionPath = path.resolve(__dirname, "../VERSION");
    return fs.readFileSync(versionPath, "utf-8").trim();
  } catch {
    return "0.0.0";
  }
};

const createProxyConfig = (supportsWebSocket = false) => ({
  target: devProxyTarget,
  changeOrigin: true,
  ws: supportsWebSocket,
});

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(getVersion()),
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": createProxyConfig(true),
      "/uploads": createProxyConfig(),
    },
  },
});
