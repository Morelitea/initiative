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
 * Whether this guild shows members' real names, or the handles they picked.
 *
 * Handles are the default. A guild listed in the community directory is not
 * asked — people who walk into a public space are known by a handle — so the
 * card is absent there rather than present and unusable.
 */
export const GuildNameDisplayPanel = () => {
  const { activeGuild, refreshGuilds, updateGuildInState } = useGuilds();
  const { t } = useTranslation("guilds");
  const [saving, setSaving] = useState(false);

  if (!activeGuild || activeGuild.is_community) return null;

  const showNames = activeGuild.show_member_names;

  const handleToggle = async (next: boolean) => {
    setSaving(true);
    try {
      const result = (await updateGuildApiV1GuildsGuildIdPatch(activeGuild.id, {
        show_member_names: next,
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
        <CardTitle>{t("nameDisplay.title")}</CardTitle>
        <CardDescription>{t("nameDisplay.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <Label htmlFor="show-member-names">{t("nameDisplay.toggleLabel")}</Label>
            <p className="text-muted-foreground text-sm">{t("nameDisplay.toggleHint")}</p>
          </div>
          <Switch
            id="show-member-names"
            checked={showNames}
            onCheckedChange={handleToggle}
            disabled={saving}
          />
        </div>
      </CardContent>
    </Card>
  );
};
