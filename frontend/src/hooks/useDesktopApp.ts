import { Capacitor } from "@capacitor/core";
import { useRouter } from "@tanstack/react-router";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import type { NotificationRead } from "@/api/generated/initiativeAPI.schemas";
import {
  listNotificationsApiV1NotificationsGet,
  readNotificationAlertApiV1NotificationsNotificationIdAlertGet,
} from "@/api/generated/notifications/notifications";
import { notificationLink, notificationText } from "@/components/notifications/notificationLine";
import { useNotificationStreamConnected } from "@/hooks/useNotificationStream";
import { useMarkNotificationRead, useNotifications } from "@/hooks/useNotifications";
import { drawBadge, setAlertHandler } from "@/lib/desktopAlerts";
import Desktop from "@/plugins/desktop";

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
  const { t } = useTranslation("guilds");
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
      labels: {
        open: t("notifications.desktop.open"),
        quit: t("notifications.desktop.quit"),
        tooltip:
          unread > 0
            ? t("notifications.desktop.unread", { count: unread })
            : t("notifications.desktop.app"),
      },
    }).catch(() => {});
  }, [desktop, unread, t]);

  // Signing out takes the count with it.
  useEffect(() => {
    if (!desktop) {
      return;
    }
    return () => {
      void Desktop.setBadge({ count: 0 }).catch(() => {});
    };
  }, [desktop]);

  useEffect(() => {
    if (!desktop) {
      return;
    }
    const announce = async (id: number) => {
      const { notification, redacted } =
        await readNotificationAlertApiV1NotificationsNotificationIdAlertGet(id);
      if (notification.read_at) {
        return;
      }
      shown.current.set(String(id), notification);
      await Desktop.notify(
        redacted
          ? { title: redacted.title, body: redacted.body, tag: String(id) }
          : {
              title: notificationText(
                notification,
                t as (key: string, options?: Record<string, unknown>) => string
              ),
              tag: String(id),
            }
      );
    };
    const summarise = async () => {
      const { unread_count: count } = await listNotificationsApiV1NotificationsGet({
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
      if (notification && !notification.read_at) {
        markRead.mutate(notification.id);
      }
      const target = notification ? notificationLink(notification) : null;
      if (target) {
        // As the bell opens it: a query string stays search, not path.
        router.navigate(target.includes("?") ? { href: target } : { to: target });
      } else {
        router.navigate({ to: "/notifications" });
      }
    });
    return () => {
      setAlertHandler(null);
      void listener.then((handle) => handle.remove());
    };
  }, [desktop, t, router, markRead.mutate]);
};
