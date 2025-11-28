import path from "path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const devProxyTarget = process.env.VITE_DEV_PROXY_TARGET ?? "http://localhost:8000";

const createProxyConfig = (supportsWebSocket = false) => ({
  target: devProxyTarget,
  changeOrigin: true,
  ws: supportsWebSocket,
});

export default defineConfig({
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
