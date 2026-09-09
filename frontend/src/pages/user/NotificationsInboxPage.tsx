import { useRouter } from "@tanstack/react-router";
import { Check, CheckCheck, Loader2, Trash2, Undo2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { NotificationRead } from "@/api/generated/initiativeAPI.schemas";
import { notificationLink, notificationText } from "@/components/notifications/notificationLine";
import { Button } from "@/components/ui/button";
import { RelativeTime } from "@/components/ui/relative-time";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import {
  useDismissNotification,
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useMarkNotificationUnread,
  useNotificationHistory,
} from "@/hooks/useNotifications";

type Filter = "all" | "unread" | "personal";

const FILTERS: Filter[] = ["all", "unread", "personal"];

/** Day buckets, so a long list reads as a timeline rather than a wall. */
const dayKey = (iso: string): string => iso.slice(0, 10);

const dayLabel = (
  key: string,
  t: (key: string, options?: Record<string, unknown>) => string
): string => {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (key === today.toISOString().slice(0, 10)) return t("notifications.inbox.today");
  if (key === yesterday.toISOString().slice(0, 10)) return t("notifications.inbox.yesterday");
  return new Date(`${key}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
};

/**
 * The record: everything that has happened, read and unread.
 *
 * Distinct from the bell's popover, which holds only what is still unread —
 * the working set. Neither is a shortened version of the other; they answer
 * "what is left for me" and "what happened".
 */
export const NotificationsInboxPage = () => {
  const { t } = useTranslation(["guilds", "common"]);
  const { user } = useAuth();
  const router = useRouter();
  const [filter, setFilter] = useState<Filter>("all");
  const [guildId, setGuildId] = useState<number | undefined>(undefined);

  const { guilds } = useGuilds();
  const history = useNotificationHistory({
    enabled: Boolean(user),
    unreadOnly: filter === "unread",
    personalOnly: filter === "personal",
    guildId,
  });

  const markRead = useMarkNotificationRead();
  const markUnread = useMarkNotificationUnread();
  const dismiss = useDismissNotification();
  const markAll = useMarkAllNotificationsRead();

  const rows = useMemo(
    () => history.data?.pages.flatMap((page) => page.notifications) ?? [],
    [history.data]
  );

  const days = useMemo(() => {
    const buckets = new Map<string, NotificationRead[]>();
    for (const row of rows) {
      const key = dayKey(row.created_at);
      const bucket = buckets.get(key);
      if (bucket) bucket.push(row);
      else buckets.set(key, [row]);
    }
    return [...buckets.entries()];
  }, [rows]);

  const guildName = (id: number | null | undefined): string | null => {
    if (id === null || id === undefined) return null;
    return guilds?.find((guild) => guild.id === id)?.name ?? null;
  };

  const open = (notification: NotificationRead) => {
    if (!notification.read_at) markRead.mutate(notification.id);
    const target = notificationLink(notification);
    if (target) router.navigate({ to: target });
  };

  if (!user) return null;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-semibold text-xl">{t("notifications.inbox.title")}</h1>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => markAll.mutate()}
          disabled={markAll.isPending}
        >
          <CheckCheck className="h-4 w-4" />
          {t("notifications.markAllRead")}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border p-0.5">
          {FILTERS.map((value) => (
            <Button
              key={value}
              variant={filter === value ? "secondary" : "ghost"}
              size="sm"
              className="h-7"
              onClick={() => setFilter(value)}
            >
              {t(`notifications.inbox.filters.${value}`)}
            </Button>
          ))}
        </div>
        {(guilds?.length ?? 0) > 1 && (
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={guildId ?? ""}
            aria-label={t("notifications.inbox.filterByCommunity")}
            onChange={(event) =>
              setGuildId(event.target.value ? Number(event.target.value) : undefined)
            }
          >
            <option value="">{t("notifications.inbox.allCommunities")}</option>
            {guilds?.map((guild) => (
              <option key={guild.id} value={guild.id}>
                {guild.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {history.isLoading ? (
        <div className="flex items-center justify-center py-12 text-muted-foreground text-sm">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          {t("notifications.loadingNotifications")}
        </div>
      ) : rows.length === 0 ? (
        <p className="py-12 text-center text-muted-foreground text-sm">
          {t("notifications.inbox.empty")}
        </p>
      ) : (
        <div className="space-y-6">
          {days.map(([key, bucket]) => (
            <section key={key} className="space-y-1">
              <h2 className="font-semibold text-muted-foreground text-xs uppercase tracking-wide">
                {dayLabel(key, t as (k: string, o?: Record<string, unknown>) => string)}
              </h2>
              <ul className="divide-y rounded-md border">
                {bucket.map((notification) => (
                  <li
                    key={notification.id}
                    className="group flex items-start gap-3 px-3 py-3 transition hover:bg-accent/40"
                  >
                    <button
                      type="button"
                      className="flex-1 text-left"
                      onClick={() => open(notification)}
                    >
                      <p
                        className={`text-sm ${notification.read_at ? "text-muted-foreground" : "text-foreground"}`}
                      >
                        {notificationText(
                          notification,
                          t as (k: string, o?: Record<string, unknown>) => string
                        )}
                      </p>
                      <p className="mt-1 flex items-center gap-2 text-muted-foreground text-xs">
                        {guildName(notification.guild_id) && (
                          <span>{guildName(notification.guild_id)}</span>
                        )}
                        <RelativeTime date={notification.created_at} />
                      </p>
                    </button>
                    <div className="flex items-center gap-1 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        aria-label={
                          notification.read_at
                            ? t("notifications.inbox.markUnread")
                            : t("notifications.inbox.markRead")
                        }
                        onClick={() =>
                          notification.read_at
                            ? markUnread.mutate(notification.id)
                            : markRead.mutate(notification.id)
                        }
                      >
                        {notification.read_at ? (
                          <Undo2 className="h-3.5 w-3.5" />
                        ) : (
                          <Check className="h-3.5 w-3.5" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        aria-label={t("notifications.inbox.dismiss")}
                        onClick={() => dismiss.mutate(notification.id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                    {!notification.read_at && (
                      <span aria-hidden className="mt-2 h-2 w-2 shrink-0 rounded-full bg-primary" />
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))}

          {history.hasNextPage && (
            <div className="flex justify-center">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void history.fetchNextPage()}
                disabled={history.isFetchingNextPage}
              >
                {history.isFetchingNextPage
                  ? t("common:loading")
                  : t("notifications.inbox.loadMore")}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
