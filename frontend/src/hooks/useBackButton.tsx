import { useEffect, useRef } from "react";
import { useRouter } from "@tanstack/react-router";
import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
import { toast } from "sonner";

const EXIT_TIMEOUT_MS = 2000;

export const useBackButton = () => {
  const router = useRouter();
  const lastBackPressRef = useRef<number>(0);

  useEffect(() => {
    if (!Capacitor.isNativePlatform()) {
      return;
    }

    const listener = App.addListener("backButton", () => {
      // Check if we can navigate back in router history
      // window.history.length > 1 indicates we have history to go back to
      if (window.history.length > 1) {
        router.history.back();
      } else {
        const now = Date.now();
        if (now - lastBackPressRef.current < EXIT_TIMEOUT_MS) {
          App.exitApp();
        } else {
          lastBackPressRef.current = now;
          toast("Press back again to exit");
        }
      }
    });

    return () => {
      listener.then((l) => l.remove());
    };
  }, [router]);
};
