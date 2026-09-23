/**
 * Which community receives this deployment's operations work (platform
 * settings → Intake).
 *
 * Who to contact comes first, and stands on its own: a deployment that routes
 * nothing anywhere still tells people whom to write to.
 *
 * Then the community. Which project each stream lands in is that community's
 * own setting, made by its superadmin under Community settings → Intake; this
 * page names the community, says which streams it currently receives, and
 * links there.
 */

import { Link } from "@tanstack/react-router";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { type IntakeSettingsRead, IntakeStream } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/useAuth";
import {
  useIntakeSettings,
  useUpdateIntakeGeneralContact,
  useUpdateIntakeStreamContact,
  useUpdateOperationsGuild,
} from "@/hooks/useIntakeSettings";
import { usePlatformGuilds } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { guildPath } from "@/lib/guildUrl";
import { Capability, hasCapability } from "@/lib/permissions";

/** Sentinel for "no community", which a Select cannot express with "". */
const NONE = "none";

/** Every stream, in the order the server declares them. */
const STREAMS = Object.values(IntakeStream);

export const SettingsIntakePage = () => {
  const { t } = useTranslation("intake");
  const { user } = useAuth();
  const isOwner = hasCapability(user, Capability.configManage);

  const {
    data: settings,
    isLoading,
    isFetching,
    isError: failed,
    refetch,
  } = useIntakeSettings({ enabled: isOwner });
  const { data: guilds } = usePlatformGuilds({ enabled: isOwner });

  const settled = !failed && !isFetching;

  const [clearing, setClearing] = useState(false);

  const updateGuild = useUpdateOperationsGuild({
    onError: (err) => toast.error(getErrorMessage(err, "intake:guild.saveError")),
  });

  if (!isOwner) {
    return <p className="text-muted-foreground text-sm">{t("ownerOnly")}</p>;
  }

  // A read that failed is a different state from a deployment that has
  // configured nothing, and says so. The picker stays out of reach until the
  // current value is known.
  if (failed) {
    return (
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("loadFailed.title")}</CardTitle>
          <CardDescription>{t("loadFailed.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={() => refetch()}>
            {t("loadFailed.retry")}
          </Button>
        </CardContent>
      </Card>
    );
  }

  const boundGuildId = settings?.operations_guild_id ?? null;
  const boundGuildName = settings?.operations_guild_name ?? "";
  const receiving = new Set(settings?.receiving ?? []);

  return (
    <div className="space-y-6">
      {settings ? <ContactsCard settings={settings} settled={settled} /> : null}

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("guild.title")}</CardTitle>
          <CardDescription>{t("guild.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label htmlFor="operations-guild">{t("guild.label")}</Label>
          <Select
            value={boundGuildId === null ? NONE : String(boundGuildId)}
            disabled={isLoading || !settled || updateGuild.isPending}
            onValueChange={(value) => {
              // Clearing it stops every stream at once, so it is confirmed;
              // choosing a different one is an ordinary change.
              if (value === NONE) {
                setClearing(true);
                return;
              }
              updateGuild.mutate({ guild_id: Number(value) });
            }}
          >
            <SelectTrigger id="operations-guild" className="max-w-md">
              <SelectValue placeholder={t("guild.placeholder")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>{t("guild.none")}</SelectItem>
              {(guilds ?? []).map((guild) => (
                <SelectItem key={guild.id} value={String(guild.id)}>
                  {guild.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-sm">{t("guild.helpText")}</p>

          {boundGuildId !== null ? (
            <div className="space-y-3 border-t pt-4">
              <ul className="space-y-2">
                {STREAMS.map((stream) => (
                  <li key={stream} className="flex items-center justify-between gap-2 text-sm">
                    <span>{t(`streams.${stream}.title`)}</span>
                    <Badge variant={receiving.has(stream) ? "default" : "outline"}>
                      {receiving.has(stream) ? t("stream.receiving") : t("stream.notReceiving")}
                    </Badge>
                  </li>
                ))}
              </ul>
              <p className="text-muted-foreground text-sm">
                {t("guild.setUpInCommunity", { name: boundGuildName })}{" "}
                <Link
                  to={guildPath(boundGuildId, "/settings/intake")}
                  className="font-medium text-primary underline-offset-4 hover:underline"
                >
                  {t("guild.openCommunitySettings", { name: boundGuildName })}
                </Link>
              </p>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={clearing}
        onOpenChange={setClearing}
        title={t("guild.clearTitle")}
        description={t("guild.clearBody")}
        confirmLabel={t("guild.clearConfirm")}
        onConfirm={() => updateGuild.mutate({ guild_id: null })}
      />
    </div>
  );
};

/**
 * Who a notice tells somebody to contact: one general address, and one per
 * stream. A stream left blank uses the general address — never another
 * stream's — and with neither set the notice names nobody.
 */
const ContactsCard = ({
  settings,
  settled,
}: {
  settings: IntakeSettingsRead;
  settled: boolean;
}) => {
  const { t } = useTranslation("intake");
  const saved = useMemo(
    () => ({
      general: settings.general_contact_email ?? "",
      streams: Object.fromEntries(
        STREAMS.map((stream) => [stream, settings.contact_emails?.[stream] ?? ""])
      ) as Record<IntakeStream, string>,
    }),
    [settings]
  );
  const [draft, setDraft] = useState(saved);
  // A save, or another tab's, replaces what the form started from.
  useEffect(() => setDraft(saved), [saved]);

  const updateGeneral = useUpdateIntakeGeneralContact();
  const updateStream = useUpdateIntakeStreamContact();
  const saving = updateGeneral.isPending || updateStream.isPending;
  const changed =
    draft.general.trim() !== saved.general ||
    STREAMS.some((stream) => draft.streams[stream].trim() !== saved.streams[stream]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const email = (value: string) => value.trim() || null;
    try {
      if (draft.general.trim() !== saved.general) {
        await updateGeneral.mutateAsync({ email: email(draft.general) });
      }
      for (const stream of STREAMS) {
        if (draft.streams[stream].trim() !== saved.streams[stream]) {
          await updateStream.mutateAsync({ stream, body: { email: email(draft.streams[stream]) } });
        }
      }
      toast.success(t("contacts.saved"));
    } catch (err) {
      toast.error(getErrorMessage(err, "intake:contacts.saveError"));
    }
  };

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("contacts.title")}</CardTitle>
        <CardDescription>{t("contacts.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="max-w-md space-y-4" onSubmit={onSubmit}>
          <div className="space-y-2">
            <Label htmlFor="intake-contact-general">{t("contacts.generalLabel")}</Label>
            <Input
              id="intake-contact-general"
              type="email"
              value={draft.general}
              placeholder={t("contacts.generalPlaceholder")}
              disabled={!settled || saving}
              onChange={(event) => setDraft({ ...draft, general: event.target.value })}
            />
          </div>
          {STREAMS.map((stream) => (
            <div key={stream} className="space-y-2">
              <Label htmlFor={`intake-contact-${stream}`}>{t(`streams.${stream}.title`)}</Label>
              <Input
                id={`intake-contact-${stream}`}
                type="email"
                value={draft.streams[stream]}
                placeholder={t("contacts.streamPlaceholder")}
                disabled={!settled || saving}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    streams: { ...draft.streams, [stream]: event.target.value },
                  })
                }
              />
            </div>
          ))}
          <Button type="submit" disabled={!settled || saving || !changed}>
            {saving ? t("contacts.saving") : t("contacts.save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
};
