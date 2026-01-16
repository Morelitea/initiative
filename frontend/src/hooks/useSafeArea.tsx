import { useEffect } from "react";
import { Capacitor } from "@capacitor/core";
import { SafeArea, SystemBarsStyle } from "@capacitor-community/safe-area";

/**
 * Configure the native system bars for mobile platforms.
 * Uses @capacitor-community/safe-area for edge-to-edge mode with proper insets.
 * The plugin automatically sets env(safe-area-inset-*) CSS values on Android.
 */
export const useSafeArea = () => {
  useEffect(() => {
    if (!Capacitor.isNativePlatform()) {
      return;
    }

    // Add native platform class for CSS targeting
    document.documentElement.classList.add("native-platform");
    if (Capacitor.getPlatform() === "android") {
      document.documentElement.classList.add("native-android");
    } else if (Capacitor.getPlatform() === "ios") {
      document.documentElement.classList.add("native-ios");
    }

    const configureSystemBars = async () => {
      try {
        const isDark = document.documentElement.classList.contains("dark");

        // Set system bars icon style (light icons on dark bg, dark icons on light bg)
        // In edge-to-edge mode, system bars are transparent - app bg shows through
        await SafeArea.setSystemBarsStyle({
          style: isDark ? SystemBarsStyle.Dark : SystemBarsStyle.Light,
        });
      } catch (error) {
        console.error("Failed to configure system bars", error);
      }
    };

    void configureSystemBars();

    // Listen for theme changes to update system bar icon colors
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.attributeName === "class") {
          void configureSystemBars();
        }
      });
    });

    observer.observe(document.documentElement, { attributes: true });

    return () => {
      observer.disconnect();
      document.documentElement.classList.remove("native-platform", "native-android", "native-ios");
    };
  }, []);
};
