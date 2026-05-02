import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { updateGuildApiV1GuildsGuildIdPatch } from "@/api/generated/guilds/guilds";
import type { GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useGuilds } from "@/hooks/useGuilds";
import { getErrorMessage } from "@/lib/errorMessage";

export const RetentionSettingCard = () => {
  const { activeGuild, updateGuildInState } = useGuilds();
  const { t } = useTranslation(["guilds", "common"]);
  const [retentionDays, setRetentionDays] = useState<number>(90);
  // Named for the switch's "Never auto-purge" label so checked={neverPurge}
  // reads directly. true = retention disabled (PATCH sends null); false =
  // auto-purge after retentionDays days.
  const [neverPurge, setNeverPurge] = useState<boolean>(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeGuild) return;
    // retention_days is authoritative: a positive integer means
    // "auto-purge after N days"; explicit null means "user chose never".
    // The backend seeds a guild_settings row at guild creation, so missing
    // rows aren't a possibility here.
    if (typeof activeGuild.retention_days === "number" && activeGuild.retention_days > 0) {
      setRetentionDays(activeGuild.retention_days);
      setNeverPurge(false);
    } else if (activeGuild.retention_days === null) {
      setRetentionDays(90);
      setNeverPurge(true);
    }
  }, [activeGuild]);

  const handleSave = async () => {
    if (!activeGuild) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const result = await (updateGuildApiV1GuildsGuildIdPatch(activeGuild.id, {
        retention_days: neverPurge ? null : retentionDays,
      } as Parameters<
        typeof updateGuildApiV1GuildsGuildIdPatch
      >[1]) as unknown as Promise<GuildRead>);
      updateGuildInState(result);
      setMessage(t("settings.retentionUpdatedSuccessfully"));
    } catch (err) {
      console.error(err);
      setError(getErrorMessage(err, "guilds:settings.unableToUpdate"));
    } finally {
      setSaving(false);
    }
  };

  if (!activeGuild) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.retentionTitle")}</CardTitle>
        <CardDescription>{t("settings.retentionDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <Switch
              id="retention-never-purge"
              checked={neverPurge}
              onCheckedChange={setNeverPurge}
            />
            <Label htmlFor="retention-never-purge">{t("settings.retentionNeverLabel")}</Label>
          </div>
          <div className="space-y-2">
            <Label htmlFor="retention-days">{t("settings.retentionDaysLabel")}</Label>
            <Input
              id="retention-days"
              type="number"
              min={1}
              max={3650}
              value={retentionDays}
              disabled={neverPurge}
              onChange={(event) => setRetentionDays(Number(event.target.value) || 1)}
              className="max-w-40"
            />
          </div>
          {error ? <p className="text-destructive text-sm">{error}</p> : null}
          {message ? <p className="text-primary text-sm">{message}</p> : null}
          <Button onClick={handleSave} disabled={saving}>
            {saving ? t("settings.saving") : t("settings.saveChanges")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};
