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
};

export default config;
