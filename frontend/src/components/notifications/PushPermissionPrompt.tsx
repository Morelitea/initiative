import { useEffect, useState } from "react";
import { X } from "lucide-react";

import { getItem, setItem } from "@/lib/storage";
import { Button } from "@/components/ui/button";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useAuth } from "@/hooks/useAuth";

const DISMISS_STORAGE_KEY = "push-prompt-dismissed";
const SHOW_DELAY_MS = 3000;

export const PushPermissionPrompt = () => {
  const { permissionStatus, requestPermission, isSupported } = usePushNotifications();
  const { user } = useAuth();
  const [show, setShow] = useState(false);

  useEffect(() => {
    // Don't show if:
    // - Not supported (web platform)
    // - Not logged in
    // - Already dismissed
    // - Permission already granted or denied
    if (!isSupported || !user) {
      return;
    }

    if (permissionStatus !== "prompt") {
      return;
    }

    const wasDismissed = getItem(DISMISS_STORAGE_KEY);
    if (wasDismissed) {
      return;
    }

    // Show banner after delay
    const timer = setTimeout(() => {
      setShow(true);
    }, SHOW_DELAY_MS);

    return () => clearTimeout(timer);
  }, [isSupported, user, permissionStatus]);

  const handleDismiss = () => {
    setItem(DISMISS_STORAGE_KEY, "true");
    setShow(false);
  };

  const handleEnable = async () => {
    try {
      await requestPermission();
      setShow(false);
    } catch (err) {
      console.error("Failed to request push permission:", err);
    }
  };

  if (!show) {
    return null;
  }

  return (
    <div className="border-b border-blue-200 bg-blue-50 px-4 py-3 dark:border-blue-900 dark:bg-blue-950/30">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-blue-900 dark:text-blue-100">
            Enable Push Notifications
          </p>
          <p className="mt-0.5 text-sm text-blue-700 dark:text-blue-300">
            Get notified about new tasks, mentions, and more
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleDismiss}
            className="text-blue-700 hover:text-blue-900 dark:text-blue-300 dark:hover:text-blue-100"
          >
            <X className="mr-1 h-4 w-4" />
            Dismiss
          </Button>
          <Button
            size="sm"
            onClick={handleEnable}
            className="bg-blue-600 text-white hover:bg-blue-700 dark:bg-blue-700 dark:hover:bg-blue-600"
          >
            Enable
          </Button>
        </div>
      </div>
    </div>
  );
};
