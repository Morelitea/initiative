import { useEffect, useRef, useState } from "react";
import { apiClient } from "@/api/client";
import { compareVersions } from "@/hooks/useDockerHubVersion";
import { getItem, setItem } from "@/lib/storage";

const CHECK_INTERVAL = 5 * 60 * 1000; // 5 minutes
const CURRENT_VERSION = __APP_VERSION__;
const DISMISSED_VERSION_KEY = "initiative-dismissed-version";

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

        // Only show update popup if server version is newer than client version
        const isServerNewer = compareVersions(serverVersion, CURRENT_VERSION) > 0;
        if (!isServerNewer) {
          return;
        }

        // Check if user already dismissed this specific version
        const dismissedVersion = getItem(DISMISSED_VERSION_KEY);
        if (dismissedVersion === serverVersion) {
          return;
        }

        if (!hasShownNotification.current) {
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
    // Persist the dismissed version so it doesn't reappear on refresh
    if (updateAvailable.version) {
      setItem(DISMISSED_VERSION_KEY, updateAvailable.version);
    }
    setUpdateAvailable({ show: false, version: "" });
  };

  return { updateAvailable, closeDialog };
};
