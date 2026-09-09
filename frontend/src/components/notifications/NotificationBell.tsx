import { useRouter } from "@tanstack/react-router";
import { Bell, CheckCheck, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { NotificationRead } from "@/api/generated/initiativeAPI.schemas";
import {
  exportDownloadTarget,
  notificationLink,
  notificationText,
} from "@/components/notifications/notificationLine";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { RelativeTime } from "@/components/ui/relative-time";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useAuth } from "@/hooks/useAuth";
import { useNotificationStreamConnected } from "@/hooks/useNotificationStream";
import {
  useAllUnreadNotifications,
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
} from "@/hooks/useNotifications";
import { downloadExportArtifact } from "@/lib/exportDownload";

// How often the bell asks on its own, which is only ever when there is no
// channel to ask for it.
const NOTIFICATION_POLL_INTERVAL_MS = 30_000;

export const NotificationBell = () => {
  const [open, setOpen] = useState(false);
  // Rows read while the popover is open. The list is unread-only, so without
  // this they would vanish under the pointer and reflow what is beneath them.
  const [justRead, setJustRead] = useState<number[]>([]);
  // Their content, kept because the unread-only query stops returning them the
  // moment the read lands.
  const readWhileOpen = useRef(new Map<number, NotificationRead>());
  const router = useRouter();
  const { user } = useAuth();
  // "tasks" is loaded alongside so the export download's cross-namespace
  // toast keys (tasks:export.*) are available when clicked from the bell.
  const { t } = useTranslation(["guilds", "tasks"]);
  const isEnabled = Boolean(user);
  const streamConnected = useNotificationStreamConnected();

  // Everything still unread, every page of it. The popover is the working set
  // — what is left to deal with — which is what makes a number on the bell
  // unnecessary: you do not need to be told how many are waiting by something
  // you can open and see. Stopping at one page would break that promise for
  // exactly the people with most to look at.
  //
  // A connected tab holds no polling timer. The channel refetches the inbox
  // the moment it moves, and it reaches every worker rather than the one that
  // happened to write the row. What a timer used to cover was the channel
  // itself going quiet, and the server now says so when that has happened.
  // With no socket at all (a proxy that drops upgrades, an offline tab) there
  // is nothing to say it, so the poll stands.
  const notificationsQuery = useAllUnreadNotifications({
    enabled: isEnabled,
    refetchInterval: streamConnected ? false : NOTIFICATION_POLL_INTERVAL_MS,
  });

  const markReadMutation = useMarkNotificationRead();

  const markAllMutation = useMarkAllNotificationsRead();

  if (!user) {
    return null;
  }

  const unread = notificationsQuery.notifications;
  // A row read while the popover is open keeps its place, dimmed, until the
  // popover closes. The list is unread-only, so without this it would vanish
  // under the pointer and reflow everything beneath it.
  const held = justRead
    .map((id) => readWhileOpen.current.get(id))
    .filter((row): row is NotificationRead => row !== undefined);
  // Deduped by id: a row can be in both while the refetch that drops it from
  // the unread list is still in flight.
  const notifications = [
    ...new Map([...unread, ...held].map((row) => [row.id, row])).values(),
  ].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const hasNotifications = notifications.length > 0;
  // A dot, not a number. The popover shows every unread item, so there is
  // nothing for a count to summarise.
  const unreadCount = notificationsQuery.unreadCount;
  const hasUnread = unreadCount > 0;

  const handleNotificationClick = async (notification: NotificationRead) => {
    // Not awaited: the read is applied to the cache as it is sent, so the dot
    // and the badge have already moved, and nothing below depends on the
    // server having answered. Waiting for it only ever showed as a stall
    // between the click and the page it opens.
    if (!notification.read_at) {
      readWhileOpen.current.set(notification.id, notification);
      setJustRead((seen) => [...seen, notification.id]);
      markReadMutation.mutate(notification.id);
    }
    // A finished export is fetched, not navigated to: the artifact lives
    // behind the job-gated download endpoint, so the click IS the download.
    const exportTarget = exportDownloadTarget(notification);
    if (exportTarget) {
      setOpen(false);
      await downloadExportArtifact(
        exportTarget.guildId,
        exportTarget.jobId,
        t as (key: string, options?: Record<string, unknown>) => string,
        exportTarget.source,
        exportTarget.format
      );
      return;
    }
    const target = notificationLink(notification);
    if (target) {
      router.navigate({ to: target });
      setOpen(false);
    }
  };

  const renderContent = () => {
    if (notificationsQuery.isLoading) {
      return (
        <div className="flex items-center justify-center py-8 text-muted-foreground text-sm">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          {t("notifications.loadingNotifications")}
        </div>
      );
    }
    if (!hasNotifications) {
      return (
        <div className="py-8 text-center text-muted-foreground text-sm">
          {t("notifications.allCaughtUp")}
        </div>
      );
    }
    return (
      <ScrollArea className="h-80">
        <ul className="divide-y">
          {notifications.map((notification) => (
            <li key={notification.id}>
              <button
                type="button"
                className={`flex w-full items-start gap-3 px-2 py-3 text-left transition hover:bg-accent/50 ${
                  justRead.includes(notification.id) ? "opacity-50" : ""
                }`}
                onClick={() => void handleNotificationClick(notification)}
              >
                <div className="flex-1">
                  <p className="text-foreground text-sm">
                    {notificationText(
                      notification,
                      t as (key: string, options?: Record<string, unknown>) => string
                    )}
                  </p>
                  <RelativeTime
                    date={notification.created_at}
                    className="mt-1 block text-muted-foreground text-xs"
                  />
                </div>
                {justRead.includes(notification.id) ? null : (
                  <span className="mt-1 h-2.5 w-2.5 rounded-full bg-primary" />
                )}
              </button>
            </li>
          ))}
        </ul>
      </ScrollArea>
    );
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          // The list settles now rather than under the pointer.
          setJustRead([]);
          readWhileOpen.current.clear();
        }
      }}
    >
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={
            hasUnread
              ? t("notifications.ariaLabelCount", { count: unreadCount })
              : t("notifications.ariaLabel")
          }
        >
          <Bell className="h-5 w-5" />
          {hasUnread ? (
            // The bell counts; the navigation does not. Here the number says
            // how much is waiting without opening anything, and it is one
            // number about one list. Repeated down a tree it would be
            // arithmetic — which is why a community, an initiative and a tool
            // each get a dot instead.
            <Badge
              aria-hidden
              className="-top-1 -right-1 absolute h-5 min-w-5 justify-center rounded-full px-1 py-0 text-[11px]"
            >
              {unreadCount > 99 ? "99+" : unreadCount}
            </Badge>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <div className="flex items-center justify-between border-b pb-2">
          <p className="font-semibold text-sm">{t("notifications.title")}</p>
          <Button
            variant="ghost"
            size="sm"
            className="text-xs"
            disabled={!hasUnread || markAllMutation.isPending}
            onClick={() => markAllMutation.mutate()}
          >
            <CheckCheck className="h-3 w-3" />
            {t("notifications.markAllRead")}
          </Button>
        </div>
        {renderContent()}
        <div className="border-t pt-2">
          <Button
            variant="ghost"
            size="sm"
            className="w-full text-xs"
            onClick={() => {
              setOpen(false);
              router.navigate({ to: "/notifications" });
            }}
          >
            {t("notifications.seeAll")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
};
