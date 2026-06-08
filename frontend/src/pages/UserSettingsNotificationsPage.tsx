import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useFcmConfig } from "@/hooks/useSettings";
import { useUpdateNotificationPreferences } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { TIMEZONE_OPTIONS } from "@/lib/timezones";

type NotificationField =
  | "email_initiative_addition"
  | "email_task_assignment"
  | "email_project_added"
  | "email_overdue_tasks"
  | "email_mentions"
  | "email_events"
  | "email_event_reminders"
  | "push_initiative_addition"
  | "push_task_assignment"
  | "push_project_added"
  | "push_overdue_tasks"
  | "push_mentions"
  | "push_events"
  | "push_event_reminders";

// Lead-time presets (minutes) for the event reminder. 0 = "at the time of the
// event"; reminders are turned off via the email/push toggles, not here.
const REMINDER_MINUTE_OPTIONS = [0, 5, 10, 15, 30, 60, 1440] as const;
const DEFAULT_REMINDER_MINUTES = 15;

interface UserSettingsNotificationsPageProps {
  user: UserRead;
  refreshUser: () => Promise<void>;
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
  // Optional control rendered full-width beneath the row (e.g. reminder lead time).
  extra?: ReactNode;
}

export const UserSettingsNotificationsPage = ({
  user,
  refreshUser,
}: UserSettingsNotificationsPageProps) => {
  const { t } = useTranslation("settings");
  const { permissionStatus, requestPermission, isSupported } = usePushNotifications();

  const { data: fcmConfig } = useFcmConfig();
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
  const [emailEvents, setEmailEvents] = useState(user.email_events ?? true);
  const [emailEventReminders, setEmailEventReminders] = useState(
    user.email_event_reminders ?? true
  );

  // Push preference states
  const [pushInitiative, setPushInitiative] = useState(user.push_initiative_addition ?? true);
  const [pushAssignment, setPushAssignment] = useState(user.push_task_assignment ?? true);
  const [pushProjectAdded, setPushProjectAdded] = useState(user.push_project_added ?? true);
  const [pushOverdue, setPushOverdue] = useState(user.push_overdue_tasks ?? true);
  const [pushMentions, setPushMentions] = useState(user.push_mentions ?? true);
  const [pushEvents, setPushEvents] = useState(user.push_events ?? true);
  const [pushEventReminders, setPushEventReminders] = useState(user.push_event_reminders ?? true);

  const [reminderMinutes, setReminderMinutes] = useState<number>(
    user.event_reminder_minutes_before ?? DEFAULT_REMINDER_MINUTES
  );

  useEffect(() => {
    setTimezone(user.timezone ?? "UTC");
    setNotificationTime(user.overdue_notification_time ?? "21:00");
    setEmailInitiative(user.email_initiative_addition ?? true);
    setEmailAssignment(user.email_task_assignment ?? true);
    setEmailProjectAdded(user.email_project_added ?? true);
    setEmailOverdue(user.email_overdue_tasks ?? true);
    setEmailMentions(user.email_mentions ?? true);
    setEmailEvents(user.email_events ?? true);
    setEmailEventReminders(user.email_event_reminders ?? true);
    setPushInitiative(user.push_initiative_addition ?? true);
    setPushAssignment(user.push_task_assignment ?? true);
    setPushProjectAdded(user.push_project_added ?? true);
    setPushOverdue(user.push_overdue_tasks ?? true);
    setPushMentions(user.push_mentions ?? true);
    setPushEvents(user.push_events ?? true);
    setPushEventReminders(user.push_event_reminders ?? true);
    setReminderMinutes(user.event_reminder_minutes_before ?? DEFAULT_REMINDER_MINUTES);
  }, [user]);

  const updateNotificationToggles = useUpdateNotificationPreferences();
  const updateNotificationSchedule = useUpdateNotificationPreferences();

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
          toast.error(t("notifications.toggleError"));
        },
      }
    );
  };

  const handleReminderMinutesChange = (raw: string) => {
    const previous = reminderMinutes;
    const next = Number(raw);
    setReminderMinutes(next);
    updateNotificationToggles.mutate(
      { event_reminder_minutes_before: next },
      {
        onSuccess: async () => {
          await refreshUser();
        },
        onError: () => {
          setReminderMinutes(previous);
          toast.error(t("notifications.toggleError"));
        },
      }
    );
  };

  const reminderLabel = (minutes: number): string => {
    if (minutes === 0) return t("notifications.reminderLeadTime.atStart");
    if (minutes >= 1440) return t("notifications.reminderLeadTime.day", { count: minutes / 1440 });
    if (minutes >= 60) return t("notifications.reminderLeadTime.hour", { count: minutes / 60 });
    return t("notifications.reminderLeadTime.minute", { count: minutes });
  };

  const handleScheduleSave = () => {
    updateNotificationSchedule.mutate(
      { timezone, overdue_notification_time: notificationTime },
      {
        onSuccess: async () => {
          await refreshUser();
          toast.success(t("notifications.scheduleSuccess"));
        },
        onError: () => {
          toast.error(t("notifications.scheduleError"));
          setTimezone(user.timezone ?? "UTC");
          setNotificationTime(user.overdue_notification_time ?? "21:00");
        },
      }
    );
  };

  const categories: NotificationCategory[] = [
    {
      label: t("notifications.categories.initiativeInvites"),
      description: t("notifications.categories.initiativeInvitesDescription"),
      emailField: "email_initiative_addition",
      emailValue: emailInitiative,
      emailSetter: setEmailInitiative,
      pushField: "push_initiative_addition",
      pushValue: pushInitiative,
      pushSetter: setPushInitiative,
    },
    {
      label: t("notifications.categories.taskAssignments"),
      description: t("notifications.categories.taskAssignmentsDescription"),
      emailField: "email_task_assignment",
      emailValue: emailAssignment,
      emailSetter: setEmailAssignment,
      pushField: "push_task_assignment",
      pushValue: pushAssignment,
      pushSetter: setPushAssignment,
    },
    {
      label: t("notifications.categories.mentions"),
      description: t("notifications.categories.mentionsDescription"),
      emailField: "email_mentions",
      emailValue: emailMentions,
      emailSetter: setEmailMentions,
      pushField: "push_mentions",
      pushValue: pushMentions,
      pushSetter: setPushMentions,
    },
    {
      label: t("notifications.categories.newProject"),
      description: t("notifications.categories.newProjectDescription"),
      emailField: "email_project_added",
      emailValue: emailProjectAdded,
      emailSetter: setEmailProjectAdded,
      pushField: "push_project_added",
      pushValue: pushProjectAdded,
      pushSetter: setPushProjectAdded,
    },
    {
      label: t("notifications.categories.overdueTasks"),
      description: t("notifications.categories.overdueTasksDescription"),
      emailField: "email_overdue_tasks",
      emailValue: emailOverdue,
      emailSetter: setEmailOverdue,
      pushField: "push_overdue_tasks",
      pushValue: pushOverdue,
      pushSetter: setPushOverdue,
    },
    {
      label: t("notifications.categories.events"),
      description: t("notifications.categories.eventsDescription"),
      emailField: "email_events",
      emailValue: emailEvents,
      emailSetter: setEmailEvents,
      pushField: "push_events",
      pushValue: pushEvents,
      pushSetter: setPushEvents,
    },
    {
      label: t("notifications.categories.eventReminders"),
      description: t("notifications.categories.eventRemindersDescription"),
      emailField: "email_event_reminders",
      emailValue: emailEventReminders,
      emailSetter: setEmailEventReminders,
      pushField: "push_event_reminders",
      pushValue: pushEventReminders,
      pushSetter: setPushEventReminders,
      extra: (
        <div className="flex items-center gap-2">
          <Label htmlFor="reminder-lead-time" className="text-muted-foreground text-sm">
            {t("notifications.reminderLeadTime.label")}
          </Label>
          <Select value={String(reminderMinutes)} onValueChange={handleReminderMinutesChange}>
            <SelectTrigger id="reminder-lead-time" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {REMINDER_MINUTE_OPTIONS.map((minutes) => (
                <SelectItem key={minutes} value={String(minutes)}>
                  {reminderLabel(minutes)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ),
    },
  ];

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("notifications.title")}</CardTitle>
        <CardDescription>{t("notifications.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Push Notifications Section (Mobile Only) */}
        {isSupported && (
          <div className="space-y-2 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">{t("notifications.pushNotifications")}</p>
                <p className="text-muted-foreground text-sm">
                  {t("notifications.pushDescription")}
                </p>
              </div>
              {permissionStatus === "granted" && (
                <Badge variant="default" className="bg-green-600 hover:bg-green-600">
                  {t("notifications.pushEnabled")}
                </Badge>
              )}
              {permissionStatus === "denied" && (
                <Badge variant="destructive">{t("notifications.pushBlocked")}</Badge>
              )}
              {permissionStatus === "prompt" && (
                <Badge variant="secondary">{t("notifications.pushNotEnabled")}</Badge>
              )}
            </div>
            {permissionStatus === "prompt" && (
              <Button onClick={requestPermission} size="sm" className="w-full">
                {t("notifications.enablePush")}
              </Button>
            )}
            {permissionStatus === "denied" && (
              <div className="rounded bg-muted p-3 text-muted-foreground text-sm">
                <p className="mb-1 font-medium">{t("notifications.pushBlockedTitle")}</p>
                <p>{t("notifications.pushBlockedDescription")}</p>
              </div>
            )}
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-3">
          <div className="space-y-2">
            <Label>{t("notifications.timezone")}</Label>
            <SearchableCombobox
              items={TIMEZONE_OPTIONS.map((tz) => ({ value: tz, label: tz }))}
              value={timezone}
              onValueChange={(value) => setTimezone(value)}
              placeholder={t("notifications.timezonePlaceholder")}
              emptyMessage={t("notifications.timezoneEmpty")}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="overdue-time">{t("notifications.overdueTime")}</Label>
            <Input
              id="overdue-time"
              type="time"
              value={notificationTime}
              onChange={(event) => setNotificationTime(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">{t("notifications.overdueTimeHelp")}</p>
          </div>
          <div className="flex items-center">
            <Button
              type="button"
              className="w-full"
              onClick={handleScheduleSave}
              disabled={updateNotificationSchedule.isPending}
            >
              {updateNotificationSchedule.isPending
                ? t("notifications.savingSchedule")
                : t("notifications.saveSchedule")}
            </Button>
          </div>
        </div>

        {/* Notification preferences table */}
        <div className="space-y-1">
          {/* Header row */}
          <div
            className={`grid items-center gap-4 border-b pb-2 ${showPushColumn ? "grid-cols-[1fr_auto_auto]" : "grid-cols-[1fr_auto]"}`}
          >
            <p className="font-medium text-muted-foreground text-sm">
              {t("notifications.categoryHeader")}
            </p>
            <p className="w-16 text-center font-medium text-muted-foreground text-sm">
              {t("notifications.emailHeader")}
            </p>
            {showPushColumn && (
              <p className="w-16 text-center font-medium text-muted-foreground text-sm">
                {t("notifications.mobileAppHeader")}
              </p>
            )}
          </div>

          {/* Data rows */}
          {categories.map((cat) => (
            <div key={cat.emailField} className="border-b last:border-b-0">
              <div
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
              {cat.extra && <div className="pb-3 pl-1">{cat.extra}</div>}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
};
