/// <reference types="@capacitor-community/safe-area" />
import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.morelitea.initiative",
  appName: "Initiative",
  webDir: "dist",
  server: {
    // Use HTTP scheme to avoid mixed content issues with self-hosted HTTP servers (LOCAL development and LAN testing)
    // androidScheme: "http",
  },
  android: {
    // Allow HTTP requests (for self-hosted servers without HTTPS) (LOCAL development and LAN testing)
    // allowMixedContent: true,
  },
  plugins: {
    // Disable built-in SystemBars insets handling - safe-area plugin handles it
    SystemBars: {
      // insetsHandling: "disable",
    },
    // SafeArea plugin config for edge-to-edge mode
    SafeArea: {
      // Detect viewport-fit changes to properly handle safe areas
      detectViewportFitCoverChanges: true,
      // Assume viewport-fit=cover initially to prevent layout jumps
      initialViewportFitCover: true,
    },
  },
};

export default config;
