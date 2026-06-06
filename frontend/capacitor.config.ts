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
    iosScheme: "https",
  },
  android: {
    // Allow HTTP requests (for self-hosted servers without HTTPS) (LOCAL development and LAN testing)
    // allowMixedContent: true,
  },
  plugins: {
    // Self-hosted OTA live updates. We drive download/set entirely from JS (manual mode):
    // the backend serves the web bundle matching its version, and useNativeUpdate downloads
    // it then prompts the user to reload. autoUpdate/directUpdate stay off so the plugin
    // never swaps the bundle on its own; appReadyTimeout arms the auto-rollback safety net
    // if a swapped-in bundle fails to call notifyAppReady().
    CapacitorUpdater: {
      autoUpdate: false,
      directUpdate: false,
      resetWhenUpdate: true,
      appReadyTimeout: 10000,
      responseTimeout: 20,
    },
    // Native splash overlay. We drive it manually (launchAutoHide off) so it can cover the
    // OTA bundle swap: useNativeUpdate shows it before CapacitorUpdater.set() reloads the
    // WebView, and the freshly-swapped bundle hides it in main.tsx after notifyAppReady().
    // Keeping it up on cold launch until that same hide() also removes the flash that would
    // otherwise appear before React mounts.
    //
    // No backgroundColor: the generated splash drawable is full-screen and theme-aware (Android
    // resolves @drawable/splash to its drawable-night variant in dark mode), so forcing a static
    // color here would only reintroduce a wrong-theme flash — a white one in dark mode, or a
    // dark one in light mode. Omitting it lets the plugin skip the fill (SplashScreen.java only
    // paints when backgroundColor is set) and the theme-correct image cover the screen.
    SplashScreen: {
      launchAutoHide: false,
      showSpinner: false,
    },
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
