/**
 * Community → Security: what this community's notifications may leave the app
 * carrying.
 *
 * The same three questions the deployment answers for everybody, asked again
 * of one community. The stricter of the pair applies, so this surface only
 * ever narrows: where the deployment has already declined a channel, or
 * already asked for redacted notifications, the switch says so instead of
 * offering the same answer twice.
 *
 * The bell inside the app is unaffected, and so is what an account is sent
 * about itself.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  useGuildNotificationPolicy,
  useUpdateGuildNotificationPolicy,
} from "@/hooks/useGuildAuthPolicy";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

export const GuildNotificationPolicySection = ({ guildId }: { guildId: number }) => {
  const { t } = useTranslation("settings");
  const query = useGuildNotificationPolicy(guildId);
  const update = useUpdateGuildNotificationPolicy(guildId);
  const [error, setError] = useState<string | null>(null);

  const saved = query.data;
  if (!saved) return null;

  // Each switch saves as it is flipped and the three go in one write, so the
  // other two are sent as they stand.
  const flip = (patch: {
    allow_push_notifications?: boolean;
    allow_email_notifications?: boolean;
    redact_notification_content?: boolean;
  }) => {
    setError(null);
    update.mutate(
      {
        allow_push_notifications: saved.allow_push_notifications,
        allow_email_notifications: saved.allow_email_notifications,
        redact_notification_content: saved.redact_notification_content,
        ...patch,
      },
      {
        onSuccess: async () => {
          await query.refetch();
          toast.success(t("guildNotifications.saved"));
        },
        onError: (err: unknown) => {
          setError(getErrorMessage(err, "settings:guildNotifications.error"));
        },
      }
    );
  };

  const rows = [
    {
      id: "guild-push-notifications",
      label: t("guildNotifications.push.label"),
      // A deployment that sends no push at all has already answered this, so
      // the line says that rather than describing a choice nobody has.
      help: !saved.push_allowed_by_platform
        ? t("guildNotifications.push.platformHelp")
        : saved.allow_push_notifications
          ? t("guildNotifications.push.onHelp")
          : t("guildNotifications.push.offHelp"),
      checked: saved.allow_push_notifications && saved.push_allowed_by_platform,
      settled: !saved.push_allowed_by_platform,
      change: (next: boolean) => flip({ allow_push_notifications: next }),
    },
    {
      id: "guild-email-notifications",
      label: t("guildNotifications.email.label"),
      help: !saved.email_allowed_by_platform
        ? t("guildNotifications.email.platformHelp")
        : saved.allow_email_notifications
          ? t("guildNotifications.email.onHelp")
          : t("guildNotifications.email.offHelp"),
      checked: saved.allow_email_notifications && saved.email_allowed_by_platform,
      settled: !saved.email_allowed_by_platform,
      change: (next: boolean) => flip({ allow_email_notifications: next }),
    },
    {
      id: "guild-redact-notifications",
      label: t("guildNotifications.redact.label"),
      help: saved.redacted_by_platform
        ? t("guildNotifications.redact.platformHelp")
        : saved.redact_notification_content
          ? t("guildNotifications.redact.onHelp")
          : t("guildNotifications.redact.offHelp"),
      checked: saved.redact_notification_content || saved.redacted_by_platform,
      settled: saved.redacted_by_platform,
      change: (next: boolean) => flip({ redact_notification_content: next }),
    },
  ];

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("guildNotifications.title")}</CardTitle>
        <CardDescription>{t("guildNotifications.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {rows.map((row) => (
          <div key={row.id} className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <Label htmlFor={row.id} className="font-medium">
                {row.label}
              </Label>
              <p className="text-muted-foreground text-sm">{row.help}</p>
            </div>
            <Switch
              id={row.id}
              checked={row.checked}
              onCheckedChange={row.change}
              disabled={update.isPending || row.settled}
            />
          </div>
        ))}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
};
