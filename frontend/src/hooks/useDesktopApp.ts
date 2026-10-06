import { Capacitor } from "@capacitor/core";
import { useRouter } from "@tanstack/react-router";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import type { NotificationRead } from "@/api/generated/initiativeAPI.schemas";
import {
  listNotifications,
  readNotificationAlert,
} from "@/api/generated/notifications/notifications";
import { notificationText, openNotification } from "@/components/notifications/notificationLine";
import { useNotificationStreamConnected } from "@/hooks/useNotificationStream";
import { useMarkNotificationRead, useNotifications } from "@/hooks/useNotifications";
import { drawBadge, setAlertHandler } from "@/lib/desktopAlerts";
import Desktop from "@/plugins/desktop";
import type { TranslateFn } from "@/types/i18n";

/** The tag a "while you were away" notification carries. */
const SUMMARY = "summary";

/**
 * The desktop app's system notifications and its unread badge.
 *
 * A notification is shown only while the window is not in front: someone
 * looking at the app has the bell. Clicking one opens it the way the bell
 * does. The badge is the bell's own unread count.
 */
export const useDesktopApp = () => {
  const desktop = Capacitor.getPlatform() === "electron";
  // "exports" is loaded alongside for a finished export's download toasts.
  const { t } = useTranslation(["communities", "exports"]);
  const router = useRouter();
  const markRead = useMarkNotificationRead();
  const streamConnected = useNotificationStreamConnected();
  const { data } = useNotifications({
    enabled: desktop,
    refetchInterval: streamConnected ? false : 30_000,
  });
  const unread = data?.unread_count ?? 0;
  // What each shown notification opens, by its tag.
  const shown = useRef(new Map<string, NotificationRead>());

  useEffect(() => {
    if (!desktop) {
      return;
    }
    void Desktop.setBadge({
      count: unread,
      overlay: drawBadge(unread),
      tooltip:
        unread > 0
          ? t("notifications.desktop.unread", { count: unread })
          : t("notifications.desktop.app"),
    }).catch(() => {});
  }, [desktop, unread, t]);

  // Signing out takes the count with it.
  useEffect(() => {
    if (!desktop) {
      return;
    }
    return () => {
      void Desktop.setBadge({ count: 0, tooltip: t("notifications.desktop.app") }).catch(() => {});
    };
  }, [desktop, t]);

  useEffect(() => {
    if (!desktop) {
      return;
    }
    const announce = async (id: number) => {
      const { notification, redacted } = await readNotificationAlert(id);
      if (notification.read_at) {
        return;
      }
      shown.current.set(String(id), notification);
      await Desktop.notify(
        redacted
          ? { title: redacted.title, body: redacted.body, tag: String(id) }
          : {
              title: notificationText(notification, t as TranslateFn),
              tag: String(id),
            }
      );
    };
    const summarise = async () => {
      const { unread_count: count } = await listNotifications({
        limit: 1,
        unread_only: true,
      });
      if (count) {
        await Desktop.notify({
          title: t("notifications.desktop.summary", { count }),
          tag: SUMMARY,
        });
      }
    };
    setAlertHandler((frame) => {
      if (document.hasFocus()) {
        return;
      }
      const sends =
        frame.action === "summary" ? [summarise()] : (frame.ids?.notifications ?? []).map(announce);
      void Promise.allSettled(sends);
    });
    const listener = Desktop.addListener("notificationClicked", ({ tag }) => {
      const notification = shown.current.get(tag);
      shown.current.delete(tag);
      const opened =
        notification &&
        openNotification(notification, {
          markRead: markRead.mutate,
          navigate: router.navigate,
          t: t as TranslateFn,
        });
      if (!opened) {
        router.navigate({ to: "/notifications" });
      }
    });
    return () => {
      setAlertHandler(null);
      void listener.then((handle) => handle.remove());
    };
  }, [desktop, t, router, markRead.mutate]);
};

/**
 * The tray's menu, named as soon as the app loads, signed in or not: an app
 * opened at sign-in waits in the tray, and the tray is its only way back.
 */
export const useDesktopTray = () => {
  const { t } = useTranslation("communities");

  useEffect(() => {
    if (Capacitor.getPlatform() !== "electron") {
      return;
    }
    void Desktop.setTray({
      open: t("notifications.desktop.open"),
      quit: t("notifications.desktop.quit"),
    }).catch(() => {});
  }, [t]);
};
