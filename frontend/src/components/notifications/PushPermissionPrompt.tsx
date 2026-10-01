import { X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { useUnreadPlaces } from "@/hooks/useNotifications";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { getItem, setItem } from "@/lib/storage";

const DISMISS_STORAGE_KEY = "push-prompt-dismissed";

/**
 * The offer to turn on push notifications, made once there is something to be
 * notified about rather than at sign-in: a notification waiting for this
 * account (someone assigned, mentioned or invited them, a message arrived).
 * The device's own permission dialog only opens from Enable.
 */
export const PushPermissionPrompt = () => {
  const { permissionStatus, requestPermission, isSupported } = usePushNotifications();
  const { user } = useAuth();
  const { t } = useTranslation("guilds");
  const [dismissed, setDismissed] = useState(() => Boolean(getItem(DISMISS_STORAGE_KEY)));
  const [answered, setAnswered] = useState(false);

  const askable =
    isSupported && Boolean(user) && permissionStatus === "prompt" && !dismissed && !answered;
  const { data: unread } = useUnreadPlaces({ enabled: askable });
  const show = askable && (unread?.places.length ?? 0) > 0;

  const handleDismiss = () => {
    setItem(DISMISS_STORAGE_KEY, "true");
    setDismissed(true);
  };

  const handleEnable = async () => {
    try {
      await requestPermission();
      setAnswered(true);
    } catch (err) {
      console.error("Failed to request push permission:", err);
    }
  };

  if (!show) {
    return null;
  }

  return (
    <div className="border-blue-200 border-b bg-blue-50 px-4 py-3 dark:border-blue-900 dark:bg-blue-950/30">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-blue-900 text-sm dark:text-blue-100">
            {t("notifications.push.enableTitle")}
          </p>
          <p className="mt-0.5 text-blue-700 text-sm dark:text-blue-300">
            {t("notifications.push.enableDescription")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleDismiss}
            className="text-blue-700 hover:text-blue-900 dark:text-blue-300 dark:hover:text-blue-100"
          >
            <X className="h-4 w-4" />
            {t("notifications.push.dismiss")}
          </Button>
          <Button
            size="sm"
            onClick={handleEnable}
            className="bg-blue-600 text-white hover:bg-blue-700 dark:bg-blue-700 dark:hover:bg-blue-600"
          >
            {t("notifications.push.enable")}
          </Button>
        </div>
      </div>
    </div>
  );
};
