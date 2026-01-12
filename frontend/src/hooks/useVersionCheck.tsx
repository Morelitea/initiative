import { useEffect, useRef, useState } from "react";
import { apiClient } from "@/api/client";

const CHECK_INTERVAL = 5 * 60 * 1000; // 5 minutes
const CURRENT_VERSION = __APP_VERSION__;

interface VersionResponse {
  version: string;
}

export const useVersionCheck = () => {
  const hasShownNotification = useRef(false);
  const [updateAvailable, setUpdateAvailable] = useState<{
    show: boolean;
    version: string;
  }>({ show: false, version: "" });

  useEffect(() => {
    const checkVersion = async () => {
      try {
        const response = await apiClient.get<VersionResponse>("/version");
        const serverVersion = response.data.version;

        if (serverVersion !== CURRENT_VERSION && !hasShownNotification.current) {
          hasShownNotification.current = true;
          setUpdateAvailable({ show: true, version: serverVersion });
        }
      } catch (error) {
        // Silently fail - version check is not critical
        console.debug("Version check failed:", error);
      }
    };

    // Check immediately on mount
    void checkVersion();

    // Then check periodically
    const interval = setInterval(() => {
      void checkVersion();
    }, CHECK_INTERVAL);

    return () => clearInterval(interval);
  }, []);

  const closeDialog = () => {
    setUpdateAvailable({ show: false, version: "" });
  };

  return { updateAvailable, closeDialog };
};
