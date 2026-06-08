import { useRouter } from "@tanstack/react-router";
import { Bell, CheckCheck, Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { NotificationRead } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useAuth } from "@/hooks/useAuth";
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from "@/hooks/useNotifications";
import { guildPath } from "@/lib/guildUrl";

// Build guild-scoped URL directly
const buildGuildPath = (guildId: number, targetPath: string): string => {
  const normalized = targetPath.startsWith("/") ? targetPath : `/${targetPath}`;
  return guildPath(guildId, normalized);
};

const resolveSmartLink = (notification: NotificationRead): string | null => {
  const data = notification.data || {};
  const guildValue = data.guild_id;
  const targetValue = data.target_path;

  let guildId: number | null = null;
  if (typeof guildValue === "number") {
    guildId = guildValue;
  } else if (typeof guildValue === "string") {
    const parsed = Number(guildValue);
    guildId = Number.isFinite(parsed) ? parsed : null;
  }

  const targetPath = typeof targetValue === "string" ? targetValue : null;
  if (guildId !== null && targetPath) {
    return buildGuildPath(guildId, targetPath);
  }

  if (typeof data.smart_link === "string" && data.smart_link) {
    try {
      const base = typeof window !== "undefined" ? window.location.origin : "http://localhost";
      const parsed = new URL(data.smart_link, base);
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    } catch {
      if (data.smart_link.startsWith("/")) {
        return data.smart_link;
      }
    }
  }

  return null;
};

const notificationLink = (notification: NotificationRead): string | null => {
  const smartLink = resolveSmartLink(notification);
  if (smartLink) {
    return smartLink;
  }
  const data = notification.data || {};
  switch (notification.type) {
    case "task_assignment":
      if (typeof data.task_id === "number") {
        return `/tasks/${data.task_id}`;
      }
      if (typeof data.task_id === "string") {
        const parsedTaskId = Number(data.task_id);
        if (Number.isFinite(parsedTaskId)) {
          return `/tasks/${parsedTaskId}`;
        }
      }
      if (typeof data.project_id === "number") {
        return `/projects/${data.project_id}`;
      }
      return null;
    case "initiative_added":
      return "/initiatives";
    case "project_added":
      if (typeof data.project_id === "number") {
        return `/projects/${data.project_id}`;
      }
      return null;
    case "user_pending_approval":
      return "/settings";
    case "mention":
      if (typeof data.document_id === "number") {
        return `/documents/${data.document_id}`;
      }
      return null;
    case "access_grant_requested":
    case "access_grant_approved":
    case "access_grant_denied":
    case "access_grant_revoked":
      // The Access tab serves both requesters (their requests) and approvers
      // (the queue). It's a platform route, not guild-scoped.
      return "/settings/admin/access";
    case "event_invitation":
    case "event_updated":
    case "event_cancelled":
    case "event_rsvp":
    case "event_reminder": {
      const eventId = Number(data.event_id);
      return Number.isFinite(eventId) ? `/events/${eventId}` : null;
    }
    default:
      return null;
  }
};

// Returns the localized level word, or null when the level is unknown (e.g.
// older notifications written before access_level was included) — callers then
// fall back to a generic, level-less message rather than mislabeling it.
const accessLevelLabel = (
  level: unknown,
  t: (key: string, options?: Record<string, unknown>) => string
): string | null => {
  if (level === "read_write") return t("notifications.accessLevelReadWrite");
  if (level === "read") return t("notifications.accessLevelRead");
  return null;
};

const notificationText = (
  notification: NotificationRead,
  t: (key: string, options?: Record<string, unknown>) => string
): string => {
  const data = notification.data || {};
  switch (notification.type) {
    case "task_assignment":
      return t("notifications.taskAssignment", {
        taskTitle: data.task_title ?? "A task",
        projectName: data.project_name ?? "a project",
        assignedBy: data.assigned_by_name
          ? t("notifications.taskAssignmentBy", { name: data.assigned_by_name })
          : "",
      });
    case "initiative_added":
      return t("notifications.initiativeAdded", {
        initiativeName: data.initiative_name ?? "initiative",
      });
    case "project_added":
      return t("notifications.projectAdded", {
        projectName: data.project_name ?? "A project",
        initiativeName: data.initiative_name ?? "an initiative",
      });
    case "user_pending_approval":
      return t("notifications.userPendingApproval", { email: data.email ?? "A user" });
    case "mention":
      // Check if it's a comment mention or document mention
      if (data.comment_id) {
        return t("notifications.mentionComment", {
          mentionedBy: data.mentioned_by_name ?? "Someone",
          contextTitle: data.context_title ?? "an item",
        });
      }
      return t("notifications.mentionDocument", {
        mentionedBy: data.mentioned_by_name ?? "Someone",
        documentTitle: data.document_title ?? "a document",
      });
    case "comment_on_task":
      return t("notifications.commentOnTask", {
        commenterName: data.commenter_name ?? "Someone",
        taskTitle: data.task_title ?? "your task",
      });
    case "comment_on_document":
      return t("notifications.commentOnDocument", {
        commenterName: data.commenter_name ?? "Someone",
        documentTitle: data.document_title ?? "your document",
      });
    case "comment_reply":
      return t("notifications.commentReply", {
        replierName: data.replier_name ?? "Someone",
        contextTitle: data.context_title ?? "an item",
      });
    case "access_grant_requested": {
      const level = accessLevelLabel(data.access_level, t);
      const requester = data.requester_name ?? "Someone";
      const guild = data.guild_name ?? "a guild";
      return level
        ? t("notifications.accessGrantRequested", { requester, level, guild })
        : t("notifications.accessGrantRequestedGeneric", { requester, guild });
    }
    case "access_grant_approved": {
      const level = accessLevelLabel(data.access_level, t);
      const guild = data.guild_name ?? "a guild";
      return level
        ? t("notifications.accessGrantApproved", { level, guild })
        : t("notifications.accessGrantApprovedGeneric", { guild });
    }
    case "access_grant_denied":
      return t("notifications.accessGrantDenied", { guild: data.guild_name ?? "a guild" });
    case "access_grant_revoked":
      return t("notifications.accessGrantRevoked", { guild: data.guild_name ?? "a guild" });
    case "event_invitation":
      return t("notifications.eventInvitation", {
        organizer: data.organizer_name ?? "Someone",
        eventTitle: data.event_title ?? "an event",
      });
    case "event_updated":
      return data.time_changed
        ? t("notifications.eventRescheduled", {
            editor: data.editor_name ?? "Someone",
            eventTitle: data.event_title ?? "an event",
          })
        : t("notifications.eventUpdated", {
            editor: data.editor_name ?? "Someone",
            eventTitle: data.event_title ?? "an event",
          });
    case "event_cancelled":
      return t("notifications.eventCancelled", {
        canceller: data.canceller_name ?? "Someone",
        eventTitle: data.event_title ?? "an event",
      });
    case "event_rsvp":
      return t("notifications.eventRsvp", {
        responder: data.responder_name ?? "Someone",
        status: data.rsvp_status ?? "responded",
        eventTitle: data.event_title ?? "an event",
      });
    case "event_reminder":
      return t("notifications.eventReminder", {
        eventTitle: data.event_title ?? "an event",
      });
    default:
      return t("notifications.defaultNotification");
  }
};

export const NotificationBell = () => {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const { user } = useAuth();
  const { t } = useTranslation("guilds");
  const isEnabled = Boolean(user);

  const notificationsQuery = useNotifications({
    refetchInterval: 30_000,
    enabled: isEnabled,
  });

  const markReadMutation = useMarkNotificationRead();

  const markAllMutation = useMarkAllNotificationsRead();

  if (!user) {
    return null;
  }

  const unreadCount = notificationsQuery.data?.unread_count ?? 0;
  const notifications = notificationsQuery.data?.notifications ?? [];
  const hasNotifications = notifications.length > 0;

  const handleNotificationClick = async (notification: NotificationRead) => {
    if (!notification.read_at) {
      try {
        await markReadMutation.mutateAsync(notification.id);
      } catch {
        // ignore errors
      }
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
                className="flex w-full items-start gap-3 px-2 py-3 text-left transition hover:bg-accent/50"
                onClick={() => void handleNotificationClick(notification)}
              >
                <div className="flex-1">
                  <p className="text-foreground text-sm">
                    {notificationText(
                      notification,
                      t as (key: string, options?: Record<string, unknown>) => string
                    )}
                  </p>
                  <p className="mt-1 text-muted-foreground text-xs">
                    {new Date(notification.created_at).toLocaleString()}
                  </p>
                </div>
                {notification.read_at ? null : (
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
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={t("notifications.ariaLabel")}
        >
          <Bell className="h-5 w-5" />
          {unreadCount > 0 ? (
            <Badge className="absolute -top-1 -right-1 h-5 min-w-5 justify-center rounded-full px-1 py-0 text-[11px]">
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
            disabled={unreadCount === 0 || markAllMutation.isPending}
            onClick={() => markAllMutation.mutate()}
          >
            <CheckCheck className="mr-1 h-3 w-3" />
            {t("notifications.markAllRead")}
          </Button>
        </div>
        {renderContent()}
      </PopoverContent>
    </Popover>
  );
};
