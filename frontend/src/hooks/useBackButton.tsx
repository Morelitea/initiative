import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
import { toast } from "sonner";

const EXIT_TIMEOUT_MS = 2000;

export const useBackButton = () => {
  const navigate = useNavigate();
  const lastBackPressRef = useRef<number>(0);

  useEffect(() => {
    if (!Capacitor.isNativePlatform()) {
      return;
    }

    const listener = App.addListener("backButton", ({ canGoBack }) => {
      if (canGoBack) {
        navigate(-1);
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
  }, [navigate]);
};
