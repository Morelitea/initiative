import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";

import {
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/api/notifications";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { Notification } from "@/types/api";
import { useAuth } from "@/hooks/useAuth";

const NOTIFICATION_QUERY_KEY = ["notifications"];

const notificationLink = (notification: Notification): string | null => {
  const data = notification.data || {};
  switch (notification.type) {
    case "task_assignment":
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
    default:
      return null;
  }
};

const notificationText = (notification: Notification): string => {
  const data = notification.data || {};
  switch (notification.type) {
    case "task_assignment":
      return `${data.task_title ?? "A task"} was assigned to you in ${data.project_name ?? "a project"}${data.assigned_by_name ? ` by ${data.assigned_by_name}` : ""}.`;
    case "initiative_added":
      return `You were added to the ${data.initiative_name ?? "initiative"}.`;
    case "project_added":
      return `${data.project_name ?? "A project"} was added to ${data.initiative_name ?? "an initiative"} you're part of.`;
    case "user_pending_approval":
      return `${data.email ?? "A user"} is awaiting approval.`;
    default:
      return "You have a new notification.";
  }
};

export const NotificationBell = () => {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user, token } = useAuth();
  const isEnabled = Boolean(user && token);

  const notificationsQuery = useQuery({
    queryKey: NOTIFICATION_QUERY_KEY,
    queryFn: fetchNotifications,
    refetchInterval: 30_000,
    enabled: isEnabled,
  });

  const markReadMutation = useMutation({
    mutationFn: (notificationId: number) => markNotificationRead(notificationId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: NOTIFICATION_QUERY_KEY });
    },
  });

  const markAllMutation = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: NOTIFICATION_QUERY_KEY });
    },
  });

  if (!user || !token) {
    return null;
  }

  const unreadCount = notificationsQuery.data?.unread_count ?? 0;
  const notifications = notificationsQuery.data?.notifications ?? [];
  const hasNotifications = notifications.length > 0;

  const handleNotificationClick = async (notification: Notification) => {
    if (!notification.read_at) {
      try {
        await markReadMutation.mutateAsync(notification.id);
      } catch {
        // ignore errors
      }
    }
    const target = notificationLink(notification);
    if (target) {
      navigate(target);
      setOpen(false);
    }
  };

  const content = useMemo(() => {
    if (notificationsQuery.isLoading) {
      return (
        <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading notifications…
        </div>
      );
    }
    if (!hasNotifications) {
      return (
        <div className="py-8 text-center text-sm text-muted-foreground">You're all caught up!</div>
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
                  <p className="text-sm text-foreground">{notificationText(notification)}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    {new Date(notification.created_at).toLocaleString()}
                  </p>
                </div>
                {notification.read_at ? null : (
                  <span className="h-2.5 w-2.5 rounded-full bg-primary mt-1" />
                )}
              </button>
            </li>
          ))}
        </ul>
      </ScrollArea>
    );
  }, [notifications, notificationsQuery.isLoading, hasNotifications]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" aria-label="Notifications">
          <Bell className="h-5 w-5" />
          {unreadCount > 0 ? (
            <Badge className="absolute -right-1 -top-1 h-5 min-w-[20px] justify-center rounded-full px-1 py-0 text-[11px]">
              {unreadCount > 99 ? "99+" : unreadCount}
            </Badge>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <div className="flex items-center justify-between border-b pb-2">
          <p className="text-sm font-semibold">Notifications</p>
          <Button
            variant="ghost"
            size="sm"
            className="text-xs"
            disabled={unreadCount === 0 || markAllMutation.isPending}
            onClick={() => markAllMutation.mutate()}
          >
            <CheckCheck className="mr-1 h-3 w-3" />
            Mark all read
          </Button>
        </div>
        {content}
      </PopoverContent>
    </Popover>
  );
};
