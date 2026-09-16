import { useState } from "react";
import { useTranslation } from "react-i18next";

import { updateGuildApiV1GuildsGuildIdPatch } from "@/api/generated/guilds/guilds";
import type { GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useGuilds } from "@/hooks/useGuilds";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

/**
 * Whether this community's members can send a help request.
 *
 * Off is the default and stays right for most installs: the sidebar's "Ask for
 * help" opens the FAQ, which answers most of what would be typed into a form.
 * Turning it on puts the form there instead, so it is worth doing only where
 * somebody reads what arrives.
 */
export const GuildSupportPanel = () => {
  const { activeGuild, refreshGuilds, updateGuildInState } = useGuilds();
  const { t } = useTranslation(["intake", "guilds"]);
  const [saving, setSaving] = useState(false);

  if (!activeGuild) return null;

  const handleToggle = async (next: boolean) => {
    setSaving(true);
    try {
      const result = (await updateGuildApiV1GuildsGuildIdPatch(activeGuild.id, {
        support_enabled: next,
      } as Parameters<typeof updateGuildApiV1GuildsGuildIdPatch>[1])) as unknown as GuildRead;
      updateGuildInState(result);
      await refreshGuilds();
    } catch (err) {
      toast.error(getErrorMessage(err, "guilds:settings.unableToUpdate"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("intake:help.title")}</CardTitle>
        <CardDescription>{t("intake:help.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <Label htmlFor="support-enabled">{t("intake:help.settingLabel")}</Label>
            <p className="text-muted-foreground text-sm">{t("intake:help.settingHelp")}</p>
          </div>
          <Switch
            id="support-enabled"
            checked={activeGuild.support_enabled}
            onCheckedChange={handleToggle}
            disabled={saving}
          />
        </div>
      </CardContent>
    </Card>
  );
};
