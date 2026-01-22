import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { Badge } from "@/components/ui/badge";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import type { User } from "@/types/api";

const FALLBACK_TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

const resolveTimezones = () => {
  const intl = Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] };
  if (typeof intl.supportedValuesOf === "function") {
    try {
      return intl.supportedValuesOf("timeZone");
    } catch {
      return FALLBACK_TIMEZONES;
    }
  }
  return FALLBACK_TIMEZONES;
};

const TIMEZONE_OPTIONS = resolveTimezones();

type NotificationField =
  | "notify_initiative_addition"
  | "notify_task_assignment"
  | "notify_project_added"
  | "notify_overdue_tasks"
  | "notify_mentions";

interface UserSettingsNotificationsPageProps {
  user: User;
  refreshUser: () => Promise<void>;
}

export const UserSettingsNotificationsPage = ({
  user,
  refreshUser,
}: UserSettingsNotificationsPageProps) => {
  const { permissionStatus, requestPermission, isSupported } = usePushNotifications();
  const [timezone, setTimezone] = useState(user.timezone ?? "UTC");
  const [notificationTime, setNotificationTime] = useState(
    user.overdue_notification_time ?? "21:00"
  );
  const [notifyInitiative, setNotifyInitiative] = useState(user.notify_initiative_addition ?? true);
  const [notifyAssignment, setNotifyAssignment] = useState(user.notify_task_assignment ?? true);
  const [notifyProjectAdded, setNotifyProjectAdded] = useState(user.notify_project_added ?? true);
  const [notifyOverdue, setNotifyOverdue] = useState(user.notify_overdue_tasks ?? true);
  const [notifyMentions, setNotifyMentions] = useState(user.notify_mentions ?? true);

  useEffect(() => {
    setTimezone(user.timezone ?? "UTC");
    setNotificationTime(user.overdue_notification_time ?? "21:00");
    setNotifyInitiative(user.notify_initiative_addition ?? true);
    setNotifyAssignment(user.notify_task_assignment ?? true);
    setNotifyProjectAdded(user.notify_project_added ?? true);
    setNotifyOverdue(user.notify_overdue_tasks ?? true);
    setNotifyMentions(user.notify_mentions ?? true);
  }, [user]);

  const updateNotificationToggles = useMutation({
    mutationFn: async (payload: Record<string, boolean>) => {
      await apiClient.patch<User>("/users/me", payload);
    },
  });

  const updateNotificationSchedule = useMutation({
    mutationFn: async (payload: Record<string, string>) => {
      await apiClient.patch<User>("/users/me", payload);
    },
  });

  const handleNotificationToggle = (
    field: NotificationField,
    nextValue: boolean,
    setter: (value: boolean) => void,
    previousValue: boolean
  ) => {
    setter(nextValue);
    updateNotificationToggles.mutate(
      { [field]: nextValue },
      {
        onSuccess: async () => {
          await refreshUser();
        },
        onError: () => {
          setter(previousValue);
          toast.error("Unable to update notification settings");
        },
      }
    );
  };

  const handleScheduleSave = () => {
    updateNotificationSchedule.mutate(
      { timezone, overdue_notification_time: notificationTime },
      {
        onSuccess: async () => {
          await refreshUser();
          toast.success("Notification schedule updated");
        },
        onError: () => {
          toast.error("Unable to update notification schedule");
          setTimezone(user.timezone ?? "UTC");
          setNotificationTime(user.overdue_notification_time ?? "21:00");
        },
      }
    );
  };

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>Notification settings</CardTitle>
        <CardDescription>
          Control which emails you receive and when overdue reminders send.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Push Notifications Section (Mobile Only) */}
        {isSupported && (
          <div className="space-y-2 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">Push Notifications</p>
                <p className="text-muted-foreground text-sm">
                  Receive real-time alerts on your device
                </p>
              </div>
              {permissionStatus === "granted" && (
                <Badge variant="default" className="bg-green-600 hover:bg-green-600">
                  Enabled
                </Badge>
              )}
              {permissionStatus === "denied" && <Badge variant="destructive">Blocked</Badge>}
              {permissionStatus === "prompt" && <Badge variant="secondary">Not enabled</Badge>}
            </div>
            {permissionStatus === "prompt" && (
              <Button onClick={requestPermission} size="sm" className="w-full">
                Enable Push Notifications
              </Button>
            )}
            {permissionStatus === "denied" && (
              <div className="text-muted-foreground bg-muted rounded p-3 text-sm">
                <p className="mb-1 font-medium">Push notifications are blocked</p>
                <p>
                  To enable push notifications, open your device settings, find this app, and enable
                  notifications.
                </p>
              </div>
            )}
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-3">
          <div className="space-y-2">
            <Label>Timezone</Label>
            <SearchableCombobox
              items={TIMEZONE_OPTIONS.map((tz) => ({ value: tz, label: tz }))}
              value={timezone}
              onValueChange={(value) => setTimezone(value)}
              placeholder="Select timezone"
              emptyMessage="No timezone found."
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="overdue-time">Overdue reminder time</Label>
            <Input
              id="overdue-time"
              type="time"
              value={notificationTime}
              onChange={(event) => setNotificationTime(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              Daily reminder time (uses the timezone above).
            </p>
          </div>
          <div className="flex items-center">
            <Button
              type="button"
              className="w-full"
              onClick={handleScheduleSave}
              disabled={updateNotificationSchedule.isPending}
            >
              {updateNotificationSchedule.isPending ? "Saving…" : "Save schedule"}
            </Button>
          </div>
        </div>
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="font-medium">Initiative invites</p>
              <p className="text-muted-foreground text-sm">
                Receive an email when you&apos;re added to a new initiative.
              </p>
            </div>
            <Switch
              checked={notifyInitiative}
              onCheckedChange={(checked) =>
                handleNotificationToggle(
                  "notify_initiative_addition",
                  checked,
                  setNotifyInitiative,
                  notifyInitiative
                )
              }
            />
          </div>
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="font-medium">Task assignments</p>
              <p className="text-muted-foreground text-sm">
                Get an hourly summary when others assign you tasks.
              </p>
            </div>
            <Switch
              checked={notifyAssignment}
              onCheckedChange={(checked) =>
                handleNotificationToggle(
                  "notify_task_assignment",
                  checked,
                  setNotifyAssignment,
                  notifyAssignment
                )
              }
            />
          </div>
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="font-medium">Mentions</p>
              <p className="text-muted-foreground text-sm">
                Get notified when someone mentions you or a task you&apos;re assigned to.
              </p>
            </div>
            <Switch
              checked={notifyMentions}
              onCheckedChange={(checked) =>
                handleNotificationToggle(
                  "notify_mentions",
                  checked,
                  setNotifyMentions,
                  notifyMentions
                )
              }
            />
          </div>
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="font-medium">New project in initiative</p>
              <p className="text-muted-foreground text-sm">
                Be alerted when projects are created inside initiatives you belong to.
              </p>
            </div>
            <Switch
              checked={notifyProjectAdded}
              onCheckedChange={(checked) =>
                handleNotificationToggle(
                  "notify_project_added",
                  checked,
                  setNotifyProjectAdded,
                  notifyProjectAdded
                )
              }
            />
          </div>
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="font-medium">Overdue tasks</p>
              <p className="text-muted-foreground text-sm">
                Receive a daily reminder for tasks past due at your scheduled time.
              </p>
            </div>
            <Switch
              checked={notifyOverdue}
              onCheckedChange={(checked) =>
                handleNotificationToggle(
                  "notify_overdue_tasks",
                  checked,
                  setNotifyOverdue,
                  notifyOverdue
                )
              }
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
