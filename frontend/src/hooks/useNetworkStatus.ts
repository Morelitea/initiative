import { useEffect, useState } from "react";
import { Capacitor, type PluginListenerHandle } from "@capacitor/core";
import { Network } from "@capacitor/network";

export interface UseNetworkStatusResult {
  isOnline: boolean;
}

/**
 * Reports whether the device currently has network connectivity.
 *
 * On native (Capacitor), uses `@capacitor/network` for accurate status.
 * On web, uses `navigator.onLine` plus `online`/`offline` window events.
 */
export const useNetworkStatus = (): UseNetworkStatusResult => {
  const [isOnline, setIsOnline] = useState<boolean>(
    typeof navigator === "undefined" ? true : navigator.onLine
  );

  useEffect(() => {
    if (Capacitor.isNativePlatform()) {
      let cancelled = false;
      let handle: PluginListenerHandle | null = null;

      Network.getStatus()
        .then((status) => {
          if (!cancelled) setIsOnline(status.connected);
        })
        .catch(() => {
          // Ignore — default state already applied.
        });

      Network.addListener("networkStatusChange", (status) => {
        if (!cancelled) setIsOnline(status.connected);
      }).then((h) => {
        if (cancelled) {
          void h.remove();
        } else {
          handle = h;
        }
      });

      return () => {
        cancelled = true;
        if (handle) void handle.remove();
      };
    }

    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    setIsOnline(navigator.onLine);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  return { isOnline };
};
