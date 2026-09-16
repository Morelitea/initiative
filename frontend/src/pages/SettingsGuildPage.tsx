import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { updateGuildApiV1GuildsGuildIdPatch } from "@/api/generated/guilds/guilds";
import type { GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { GuildArtworkPanel } from "@/components/guilds/GuildArtworkPanel";
import { GuildDiscoveryPanel } from "@/components/guilds/GuildDiscoveryPanel";
import { GuildNameDisplayPanel } from "@/components/guilds/GuildNameDisplayPanel";
import { GuildUsagePanel } from "@/components/guilds/GuildUsagePanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useGuilds } from "@/hooks/useGuilds";
import { getErrorMessage } from "@/lib/errorMessage";

export const SettingsGuildPage = () => {
  const { activeGuild, refreshGuilds, updateGuildInState } = useGuilds();
  const { t } = useTranslation(["guilds", "common"]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeGuild) {
      setName("");
      setDescription("");
      return;
    }
    setName(activeGuild.name);
    setDescription(activeGuild.description ?? "");
  }, [activeGuild]);

  const handleSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!activeGuild) {
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      const result = await (updateGuildApiV1GuildsGuildIdPatch(activeGuild.id, {
        name,
        description,
      } as Parameters<
        typeof updateGuildApiV1GuildsGuildIdPatch
      >[1]) as unknown as Promise<GuildRead>);
      updateGuildInState(result);
      await refreshGuilds();
      setSaveMessage(t("settings.updatedSuccessfully"));
    } catch (err) {
      console.error(err);
      setSaveError(getErrorMessage(err, "guilds:settings.unableToUpdate"));
    } finally {
      setSaving(false);
    }
  };

  if (!activeGuild) {
    return (
      <div className="space-y-4">
        <h2 className="font-semibold text-2xl">{t("settings.title")}</h2>
        <p className="text-muted-foreground text-sm">{t("settings.noActiveGuild")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.detailsTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSave}>
            <div className="space-y-2">
              <Label htmlFor="guild-name">{t("settings.nameLabel")}</Label>
              <Input
                id="guild-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="guild-description">{t("settings.descriptionLabel")}</Label>
              <Textarea
                id="guild-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
              />
            </div>
            {saveError ? <p className="text-destructive text-sm">{saveError}</p> : null}
            {saveMessage ? <p className="text-primary text-sm">{saveMessage}</p> : null}
            <Button type="submit" disabled={saving}>
              {saving ? t("settings.saving") : t("settings.saveChanges")}
            </Button>
          </form>
        </CardContent>
      </Card>
      <GuildArtworkPanel guild={activeGuild} />
      <GuildNameDisplayPanel />
      <GuildDiscoveryPanel />
      <GuildUsagePanel />
    </div>
  );
};
