import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const chunkGroups = [
  {
    name: "react-vendors",
    test: (id: string) => /node_modules\/(react|react-dom|react-router-dom)\//.test(id),
  },
  { name: "dnd-kit", test: (id: string) => /node_modules\/@dnd-kit\//.test(id) },
  { name: "radix-ui", test: (id: string) => /node_modules\/@radix-ui\//.test(id) },
  { name: "tanstack", test: (id: string) => /node_modules\/@tanstack\//.test(id) },
];

const manualChunks = (id: string) => {
  if (!id.includes("node_modules")) {
    return undefined;
  }
  for (const group of chunkGroups) {
    if (group.test(id)) {
      return group.name;
    }
  }
  return "vendor";
};

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8173",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
