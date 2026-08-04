import { useTranslation } from "react-i18next";

import type { MyAIConnectionRow } from "@/api/generated/initiativeAPI.schemas";
import { MyGuildAISection } from "@/components/settings/MyGuildAISection";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useMyAI } from "@/hooks/useAISettings";

interface GuildGroup {
  guildId: number;
  guildName: string;
  connections: MyAIConnectionRow[];
}

/** Group the flat `/me/ai` rows by guild, preserving first-seen order. */
const groupByGuild = (rows: MyAIConnectionRow[]): GuildGroup[] => {
  const groups: GuildGroup[] = [];
  const byId = new Map<number, GuildGroup>();
  for (const row of rows) {
    let group = byId.get(row.guild_id);
    if (!group) {
      group = { guildId: row.guild_id, guildName: row.guild_name, connections: [] };
      byId.set(row.guild_id, group);
      groups.push(group);
    }
    group.connections.push(row);
  }
  return groups;
};

/**
 * Personal, cross-guild "My AI" view. A single server aggregate (`/me/ai`) lists
 * every connection the user can reach across all their guilds; they set their
 * own key and pick which connection they use, per guild.
 */
export const UserSettingsAIPage = () => {
  const { t } = useTranslation("settings");
  const query = useMyAI();

  const content = () => {
    if (query.isLoading) {
      return <p className="text-muted-foreground text-sm">{t("ai.loading")}</p>;
    }
    if (query.isError || !query.data) {
      return <p className="text-destructive text-sm">{t("ai.loadError")}</p>;
    }
    if (query.data.length === 0) {
      return <p className="text-muted-foreground text-sm">{t("memberAI.noneAvailable")}</p>;
    }
    return (
      <div className="space-y-6">
        {groupByGuild(query.data).map((group) => (
          <MyGuildAISection
            key={group.guildId}
            guildId={group.guildId}
            guildName={group.guildName}
            connections={group.connections}
          />
        ))}
      </div>
    );
  };

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("memberAI.title")}</CardTitle>
        <CardDescription>{t("memberAI.description")}</CardDescription>
      </CardHeader>
      <CardContent>{content()}</CardContent>
    </Card>
  );
};
