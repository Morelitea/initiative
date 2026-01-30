/// <reference types="@capacitor-community/safe-area" />
import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.morelitea.initiative",
  appName: "Initiative",
  webDir: "dist",
  server: {
    // Use HTTP scheme to avoid mixed content issues with self-hosted HTTP servers (LOCAL development and LAN testing)
    // androidScheme: "http",
    hostname: "com.morelitea.initiative",
  },
  android: {
    // Allow HTTP requests (for self-hosted servers without HTTPS) (LOCAL development and LAN testing)
    // allowMixedContent: true,
  },
  plugins: {
    // Disable built-in SystemBars insets handling - safe-area plugin handles it
    SystemBars: {
      insetsHandling: "disable",
    },
    // SafeArea plugin config for edge-to-edge mode
    SafeArea: {
      // Disable viewport-fit detection to force native padding mode
      // This ensures safe area insets work on Samsung and other devices where
      // the WebView may not properly set CSS env(safe-area-inset-*) values
      detectViewportFitCoverChanges: false,
      initialViewportFitCover: false,
    },
  },
};

export default config;
