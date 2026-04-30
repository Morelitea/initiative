import { Capacitor } from "@capacitor/core";
import { KeepAwake } from "@capacitor-community/keep-awake";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { getItem, setItem } from "@/lib/storage";

const STORAGE_KEY = "initiative-keep-screen-awake";

interface KeepScreenAwakeContextValue {
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
  supported: boolean;
}

const KeepScreenAwakeContext = createContext<KeepScreenAwakeContextValue | undefined>(undefined);

const detectSupported = (): boolean => {
  if (Capacitor.isNativePlatform()) {
    return true;
  }
  return typeof navigator !== "undefined" && "wakeLock" in navigator;
};

const readStoredEnabled = (): boolean => getItem(STORAGE_KEY) === "1";

export const KeepScreenAwakeProvider = ({ children }: { children: ReactNode }) => {
  const [enabled, setEnabled] = useState<boolean>(() => readStoredEnabled());
  const supported = detectSupported();
  const sentinelRef = useRef<WakeLockSentinel | null>(null);
  const isInitialMount = useRef(true);

  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }
    setItem(STORAGE_KEY, enabled ? "1" : "0");
  }, [enabled]);

  useEffect(() => {
    if (!supported) {
      return;
    }

    let cancelled = false;
    const isNative = Capacitor.isNativePlatform();

    // If the OS keeps revoking the wake lock (battery saver, thermal
    // throttling, resource pressure), stop fighting it after a few
    // rapid releases until the user toggles off and on again.
    const RAPID_RELEASE_WINDOW_MS = 30_000;
    const RAPID_RELEASE_LIMIT = 3;
    const recentReleases: number[] = [];

    const acquire = async () => {
      if (cancelled) return;
      try {
        if (isNative) {
          await KeepAwake.keepAwake();
        } else if (document.visibilityState === "visible") {
          if (sentinelRef.current) return;
          const sentinel = await navigator.wakeLock.request("screen");
          if (cancelled) {
            void sentinel.release();
            return;
          }
          sentinelRef.current = sentinel;
          sentinel.addEventListener("release", () => {
            if (sentinelRef.current === sentinel) {
              sentinelRef.current = null;
            }
            // The OS can drop the sentinel for reasons other than tab-hide
            // (low-power mode, resource pressure). Reacquire while the tab
            // is still visible and the user still wants the lock — but
            // back off once the OS has revoked us repeatedly so we respect
            // battery saver / thermal throttling instead of fighting it.
            const now = Date.now();
            while (recentReleases.length && now - recentReleases[0] >= RAPID_RELEASE_WINDOW_MS) {
              recentReleases.shift();
            }
            recentReleases.push(now);
            const backoff = recentReleases.length >= RAPID_RELEASE_LIMIT;
            if (backoff) {
              console.warn(
                "Screen wake lock repeatedly revoked by the OS (likely battery saver); backing off."
              );
              return;
            }
            if (!cancelled && document.visibilityState === "visible") {
              void acquire();
            }
          });
        }
      } catch (error) {
        console.warn("Failed to acquire screen wake lock:", error);
      }
    };

    const release = async () => {
      try {
        if (isNative) {
          await KeepAwake.allowSleep();
        } else if (sentinelRef.current) {
          await sentinelRef.current.release();
          sentinelRef.current = null;
        }
      } catch (error) {
        console.warn("Failed to release screen wake lock:", error);
      }
    };

    if (!enabled) {
      void release();
      return () => {
        cancelled = true;
      };
    }

    void acquire();

    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        void acquire();
      } else {
        void release();
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", handleVisibility);
      void release();
    };
  }, [enabled, supported]);

  return (
    <KeepScreenAwakeContext.Provider value={{ enabled, setEnabled, supported }}>
      {children}
    </KeepScreenAwakeContext.Provider>
  );
};

export const useKeepScreenAwake = () => {
  const context = useContext(KeepScreenAwakeContext);
  if (!context) {
    throw new Error("useKeepScreenAwake must be used within a KeepScreenAwakeProvider");
  }
  return context;
};
