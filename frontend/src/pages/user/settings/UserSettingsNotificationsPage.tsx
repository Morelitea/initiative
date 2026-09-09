import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  Channel,
  NotificationCategoryRead,
  NotificationLevel,
  UserRead,
} from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import {
  useNotificationPreferences,
  useUpdateNotificationPreferences as useWritePreferences,
} from "@/hooks/useNotificationPreferences";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useFcmConfig } from "@/hooks/useSettings";
import { useUpdateNotificationPreferences } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { TIMEZONE_OPTIONS } from "@/lib/timezones";

// Lead-time presets (minutes) for the event reminder. 0 = "at the time of the
// event"; reminders are turned off with the channel switches, not here.
const REMINDER_MINUTE_OPTIONS = [0, 5, 10, 15, 30, 60, 1440] as const;
const DEFAULT_REMINDER_MINUTES = 15;

// The order the sections appear in. The registry says which group each
// category belongs to, so a category added to the backend lands in one of
// these without this file changing.
const GROUP_ORDER = ["addressed_to_me", "activity", "community", "account"] as const;

// Every channel, in column order.
const CHANNELS: Channel[] = ["in_app", "email", "push"];

const LEVELS: NotificationLevel[] = ["everything", "personal", "nothing"];

interface UserSettingsNotificationsPageProps {
  user: UserRead;
  refreshUser: () => Promise<void>;
}

export const UserSettingsNotificationsPage = ({
  user,
  refreshUser,
}: UserSettingsNotificationsPageProps) => {
  const { t } = useTranslation(["settings", "common"]);
  const { permissionStatus, requestPermission, isSupported } = usePushNotifications();

  const { data: fcmConfig } = useFcmConfig();
  const showPushColumn = fcmConfig?.enabled ?? false;

  const { data: preferences, isLoading } = useNotificationPreferences();
  const writePreferences = useWritePreferences();

  const [timezone, setTimezone] = useState(user.timezone ?? "UTC");
  const [notificationTime, setNotificationTime] = useState(
    user.overdue_notification_time ?? "21:00"
  );
  const [reminderMinutes, setReminderMinutes] = useState<number>(
    user.event_reminder_minutes_before ?? DEFAULT_REMINDER_MINUTES
  );
  const [quietStart, setQuietStart] = useState("22:00");
  const [quietEnd, setQuietEnd] = useState("07:00");

  useEffect(() => {
    setTimezone(user.timezone ?? "UTC");
    setNotificationTime(user.overdue_notification_time ?? "21:00");
    setReminderMinutes(user.event_reminder_minutes_before ?? DEFAULT_REMINDER_MINUTES);
  }, [user]);

  useEffect(() => {
    if (preferences?.quiet_hours) {
      setQuietStart(preferences.quiet_hours.start);
      setQuietEnd(preferences.quiet_hours.end);
    }
  }, [preferences?.quiet_hours]);

  const updateSchedule = useUpdateNotificationPreferences();

  // The registry decides which rows exist and which switches move; this file
  // only decides what order the sections come in.
  const grouped = useMemo(() => {
    const rows = preferences?.categories ?? [];
    return GROUP_ORDER.map((group) => ({
      group,
      rows: rows.filter((row) => row.group === group),
    })).filter((section) => section.rows.length > 0);
  }, [preferences?.categories]);

  const visibleChannels = CHANNELS.filter((channel) => channel !== "push" || showPushColumn);

  const isOn = (row: NotificationCategoryRead, channel: Channel, guildId?: number) => {
    const scoped = guildId
      ? preferences?.guilds?.find((entry) => entry.guild_id === guildId)?.categories
      : preferences?.settings;
    const stored = scoped?.[row.category]?.[channel];
    if (typeof stored === "boolean") return stored;
    return row.defaults[channel] ?? true;
  };

  const toggle = (
    row: NotificationCategoryRead,
    channel: Channel,
    next: boolean,
    guildId?: number
  ) => {
    writePreferences.mutate(
      {
        channels: [{ category: row.category, channel, enabled: next, guild_id: guildId ?? null }],
      },
      { onError: () => toast.error(t("notifications.toggleError")) }
    );
  };

  const setLevel = (guildId: number, level: NotificationLevel) => {
    writePreferences.mutate(
      { levels: [{ guild_id: guildId, level }] },
      { onError: () => toast.error(t("notifications.toggleError")) }
    );
  };

  const saveQuietHours = (enabled: boolean) => {
    writePreferences.mutate(
      enabled ? { quiet_hours: { start: quietStart, end: quietEnd } } : { clear_quiet_hours: true },
      { onError: () => toast.error(t("notifications.toggleError")) }
    );
  };

  const reminderLabel = (minutes: number): string => {
    if (minutes === 0) return t("notifications.reminderLeadTime.atStart");
    if (minutes >= 1440) return t("notifications.reminderLeadTime.day", { count: minutes / 1440 });
    if (minutes >= 60) return t("notifications.reminderLeadTime.hour", { count: minutes / 60 });
    return t("notifications.reminderLeadTime.minute", { count: minutes });
  };

  const handleReminderMinutesChange = (raw: string) => {
    const previous = reminderMinutes;
    const next = Number(raw);
    setReminderMinutes(next);
    updateSchedule.mutate(
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

  const handleScheduleSave = () => {
    updateSchedule.mutate(
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

  const gridColumns =
    visibleChannels.length === 3 ? "grid-cols-[1fr_auto_auto_auto]" : "grid-cols-[1fr_auto_auto]";

  const renderGrid = (guildId?: number) => (
    <div className="space-y-1">
      <div className={`grid items-center gap-4 border-b pb-2 ${gridColumns}`}>
        <p className="font-medium text-muted-foreground text-sm">
          {t("notifications.categoryHeader")}
        </p>
        {visibleChannels.map((channel) => (
          <p key={channel} className="w-16 text-center font-medium text-muted-foreground text-sm">
            {t(`notifications.channels.${channel}`)}
          </p>
        ))}
      </div>

      {grouped.map((section) => {
        const rows = section.rows.filter((row) => !guildId || row.guild_scoped);
        if (rows.length === 0) return null;
        return (
          <div key={section.group}>
            <p className="pt-4 pb-1 font-semibold text-muted-foreground text-xs uppercase tracking-wide">
              {t(`notifications.groups.${section.group}`)}
            </p>
            {rows.map((row) => (
              <div key={row.category} className="border-b last:border-b-0">
                <div className={`grid items-center gap-4 py-3 ${gridColumns}`}>
                  <div>
                    <p className="font-medium">{t(`notifications.categories.${row.category}`)}</p>
                    <p className="text-muted-foreground text-sm">
                      {t(`notifications.categoryDescriptions.${row.category}`)}
                    </p>
                  </div>
                  {visibleChannels.map((channel) => {
                    const mutable = row.mutable_channels.includes(channel);
                    return (
                      <div key={channel} className="flex w-16 justify-center">
                        <Switch
                          checked={mutable ? isOn(row, channel, guildId) : true}
                          disabled={!mutable || writePreferences.isPending}
                          aria-label={t("notifications.switchLabel", {
                            category: t(`notifications.categories.${row.category}`),
                            channel: t(`notifications.channels.${channel}`),
                          })}
                          onCheckedChange={(checked) => toggle(row, channel, checked, guildId)}
                        />
                      </div>
                    );
                  })}
                </div>
                {row.category === "event_reminders" && !guildId && (
                  <div className="flex items-center gap-2 pb-3 pl-1">
                    <Label htmlFor="reminder-lead-time" className="text-muted-foreground text-sm">
                      {t("notifications.reminderLeadTime.label")}
                    </Label>
                    <Select
                      value={String(reminderMinutes)}
                      onValueChange={handleReminderMinutesChange}
                    >
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
                )}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );

  return (
    <div className="space-y-6">
      {isSupported && (
        <SettingsSection
          title={t("notifications.pushNotifications")}
          description={t("notifications.pushDescription")}
          action={
            <>
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
            </>
          }
        >
          {permissionStatus === "prompt" && (
            <Button onClick={requestPermission} size="sm">
              {t("notifications.enablePush")}
            </Button>
          )}
          {permissionStatus === "denied" && (
            <div className="rounded bg-muted p-3 text-muted-foreground text-sm">
              <p className="mb-1 font-medium">{t("notifications.pushBlockedTitle")}</p>
              <p>{t("notifications.pushBlockedDescription")}</p>
            </div>
          )}
        </SettingsSection>
      )}

      <SettingsSection
        title={t("notifications.scheduleTitle")}
        description={t("notifications.scheduleDescription")}
        footer={
          <Button type="button" onClick={handleScheduleSave} disabled={updateSchedule.isPending}>
            {updateSchedule.isPending
              ? t("notifications.savingSchedule")
              : t("notifications.saveSchedule")}
          </Button>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
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
        </div>
      </SettingsSection>

      <SettingsSection
        title={t("notifications.quietHours.title")}
        description={t("notifications.quietHours.description")}
        action={
          <Switch
            checked={Boolean(preferences?.quiet_hours)}
            aria-label={t("notifications.quietHours.title")}
            onCheckedChange={saveQuietHours}
          />
        }
      >
        {preferences?.quiet_hours && (
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="quiet-start">{t("notifications.quietHours.from")}</Label>
              <Input
                id="quiet-start"
                type="time"
                value={quietStart}
                onChange={(event) => setQuietStart(event.target.value)}
                onBlur={() => saveQuietHours(true)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="quiet-end">{t("notifications.quietHours.to")}</Label>
              <Input
                id="quiet-end"
                type="time"
                value={quietEnd}
                onChange={(event) => setQuietEnd(event.target.value)}
                onBlur={() => saveQuietHours(true)}
              />
            </div>
          </div>
        )}
      </SettingsSection>

      <SettingsSection
        title={t("notifications.channelsTitle")}
        description={t("notifications.channelsDescription")}
      >
        {isLoading ? (
          <p className="text-muted-foreground text-sm">{t("common:loading")}</p>
        ) : (
          renderGrid()
        )}
      </SettingsSection>

      {(preferences?.guilds?.length ?? 0) > 0 && (
        <SettingsSection
          title={t("notifications.communities.title")}
          description={t("notifications.communities.description")}
        >
          <div className="space-y-3">
            {preferences?.guilds?.map((guild) => (
              <details key={guild.guild_id} className="rounded border">
                <summary className="flex cursor-pointer items-center justify-between gap-4 p-3">
                  <span className="font-medium">{guild.guild_name}</span>
                  <Select
                    value={guild.level}
                    onValueChange={(value) => setLevel(guild.guild_id, value as NotificationLevel)}
                  >
                    <SelectTrigger
                      className="w-56"
                      aria-label={t("notifications.communities.levelLabel", {
                        guild: guild.guild_name,
                      })}
                      onClick={(event) => event.preventDefault()}
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {LEVELS.map((level) => (
                        <SelectItem key={level} value={level}>
                          {t(`notifications.communities.levels.${level}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </summary>
                <div className="border-t p-3">
                  {guild.level === "nothing" ? (
                    <p className="text-muted-foreground text-sm">
                      {t("notifications.communities.mutedHelp")}
                    </p>
                  ) : (
                    renderGrid(guild.guild_id)
                  )}
                </div>
              </details>
            ))}
          </div>
        </SettingsSection>
      )}
    </div>
  );
};
