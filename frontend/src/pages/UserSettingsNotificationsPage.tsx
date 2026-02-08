import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
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
  | "email_initiative_addition"
  | "email_task_assignment"
  | "email_project_added"
  | "email_overdue_tasks"
  | "email_mentions"
  | "push_initiative_addition"
  | "push_task_assignment"
  | "push_project_added"
  | "push_overdue_tasks"
  | "push_mentions";

interface UserSettingsNotificationsPageProps {
  user: User;
  refreshUser: () => Promise<void>;
}

interface FCMConfigResponse {
  enabled: boolean;
}

interface NotificationCategory {
  label: string;
  description: string;
  emailField: NotificationField;
  emailValue: boolean;
  emailSetter: (v: boolean) => void;
  pushField: NotificationField;
  pushValue: boolean;
  pushSetter: (v: boolean) => void;
}

export const UserSettingsNotificationsPage = ({
  user,
  refreshUser,
}: UserSettingsNotificationsPageProps) => {
  const { permissionStatus, requestPermission, isSupported } = usePushNotifications();

  const { data: fcmConfig } = useQuery({
    queryKey: ["fcm-config"],
    queryFn: async () => {
      const res = await apiClient.get<FCMConfigResponse>("/settings/fcm-config");
      return res.data;
    },
    staleTime: 5 * 60 * 1000,
  });
  const showPushColumn = fcmConfig?.enabled ?? false;

  const [timezone, setTimezone] = useState(user.timezone ?? "UTC");
  const [notificationTime, setNotificationTime] = useState(
    user.overdue_notification_time ?? "21:00"
  );

  // Email preference states
  const [emailInitiative, setEmailInitiative] = useState(user.email_initiative_addition ?? true);
  const [emailAssignment, setEmailAssignment] = useState(user.email_task_assignment ?? true);
  const [emailProjectAdded, setEmailProjectAdded] = useState(user.email_project_added ?? true);
  const [emailOverdue, setEmailOverdue] = useState(user.email_overdue_tasks ?? true);
  const [emailMentions, setEmailMentions] = useState(user.email_mentions ?? true);

  // Push preference states
  const [pushInitiative, setPushInitiative] = useState(user.push_initiative_addition ?? true);
  const [pushAssignment, setPushAssignment] = useState(user.push_task_assignment ?? true);
  const [pushProjectAdded, setPushProjectAdded] = useState(user.push_project_added ?? true);
  const [pushOverdue, setPushOverdue] = useState(user.push_overdue_tasks ?? true);
  const [pushMentions, setPushMentions] = useState(user.push_mentions ?? true);

  useEffect(() => {
    setTimezone(user.timezone ?? "UTC");
    setNotificationTime(user.overdue_notification_time ?? "21:00");
    setEmailInitiative(user.email_initiative_addition ?? true);
    setEmailAssignment(user.email_task_assignment ?? true);
    setEmailProjectAdded(user.email_project_added ?? true);
    setEmailOverdue(user.email_overdue_tasks ?? true);
    setEmailMentions(user.email_mentions ?? true);
    setPushInitiative(user.push_initiative_addition ?? true);
    setPushAssignment(user.push_task_assignment ?? true);
    setPushProjectAdded(user.push_project_added ?? true);
    setPushOverdue(user.push_overdue_tasks ?? true);
    setPushMentions(user.push_mentions ?? true);
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

  const categories: NotificationCategory[] = [
    {
      label: "Initiative invites",
      description: "When you\u2019re added to a new initiative.",
      emailField: "email_initiative_addition",
      emailValue: emailInitiative,
      emailSetter: setEmailInitiative,
      pushField: "push_initiative_addition",
      pushValue: pushInitiative,
      pushSetter: setPushInitiative,
    },
    {
      label: "Task assignments",
      description: "Hourly summary when others assign you tasks.",
      emailField: "email_task_assignment",
      emailValue: emailAssignment,
      emailSetter: setEmailAssignment,
      pushField: "push_task_assignment",
      pushValue: pushAssignment,
      pushSetter: setPushAssignment,
    },
    {
      label: "Mentions",
      description: "When someone mentions you or comments on your work.",
      emailField: "email_mentions",
      emailValue: emailMentions,
      emailSetter: setEmailMentions,
      pushField: "push_mentions",
      pushValue: pushMentions,
      pushSetter: setPushMentions,
    },
    {
      label: "New project in initiative",
      description: "When projects are created in your initiatives.",
      emailField: "email_project_added",
      emailValue: emailProjectAdded,
      emailSetter: setEmailProjectAdded,
      pushField: "push_project_added",
      pushValue: pushProjectAdded,
      pushSetter: setPushProjectAdded,
    },
    {
      label: "Overdue tasks",
      description: "Daily reminder for tasks past due at your scheduled time.",
      emailField: "email_overdue_tasks",
      emailValue: emailOverdue,
      emailSetter: setEmailOverdue,
      pushField: "push_overdue_tasks",
      pushValue: pushOverdue,
      pushSetter: setPushOverdue,
    },
  ];

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>Notification settings</CardTitle>
        <CardDescription>
          Control which notifications you receive by channel. Bell notifications always appear
          regardless of these settings.
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
              {updateNotificationSchedule.isPending ? "Saving\u2026" : "Save schedule"}
            </Button>
          </div>
        </div>

        {/* Notification preferences table */}
        <div className="space-y-1">
          {/* Header row */}
          <div
            className={`grid items-center gap-4 border-b pb-2 ${showPushColumn ? "grid-cols-[1fr_auto_auto]" : "grid-cols-[1fr_auto]"}`}
          >
            <p className="text-muted-foreground text-sm font-medium">Category</p>
            <p className="text-muted-foreground w-16 text-center text-sm font-medium">Email</p>
            {showPushColumn && (
              <p className="text-muted-foreground w-16 text-center text-sm font-medium">
                Mobile App
              </p>
            )}
          </div>

          {/* Data rows */}
          {categories.map((cat) => (
            <div
              key={cat.emailField}
              className={`grid items-center gap-4 py-3 ${showPushColumn ? "grid-cols-[1fr_auto_auto]" : "grid-cols-[1fr_auto]"}`}
            >
              <div>
                <p className="font-medium">{cat.label}</p>
                <p className="text-muted-foreground text-sm">{cat.description}</p>
              </div>
              <div className="flex w-16 justify-center">
                <Switch
                  checked={cat.emailValue}
                  onCheckedChange={(checked) =>
                    handleNotificationToggle(
                      cat.emailField,
                      checked,
                      cat.emailSetter,
                      cat.emailValue
                    )
                  }
                />
              </div>
              {showPushColumn && (
                <div className="flex w-16 justify-center">
                  <Switch
                    checked={cat.pushValue}
                    onCheckedChange={(checked) =>
                      handleNotificationToggle(
                        cat.pushField,
                        checked,
                        cat.pushSetter,
                        cat.pushValue
                      )
                    }
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
};
