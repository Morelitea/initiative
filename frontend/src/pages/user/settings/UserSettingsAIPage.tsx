import { useTranslation } from "react-i18next";

import type { MyAIConnectionRow } from "@/api/generated/initiativeAPI.schemas";
import { MyCommunityAISection } from "@/components/settings/MyCommunityAISection";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useMyAI } from "@/hooks/useAISettings";

interface CommunityGroup {
  communityId: number;
  communityName: string;
  connections: MyAIConnectionRow[];
}

/** Group the flat `/me/ai` rows by community, preserving first-seen order. */
const groupByCommunity = (rows: MyAIConnectionRow[]): CommunityGroup[] => {
  const groups: CommunityGroup[] = [];
  const byId = new Map<number, CommunityGroup>();
  for (const row of rows) {
    let group = byId.get(row.community_id);
    if (!group) {
      group = { communityId: row.community_id, communityName: row.community_name, connections: [] };
      byId.set(row.community_id, group);
      groups.push(group);
    }
    group.connections.push(row);
  }
  return groups;
};

/**
 * Personal, cross-community "My AI" view. A single server aggregate (`/me/ai`) lists
 * every connection the user can reach across all their communities; they set their
 * own key and pick which connection they use, per community.
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
        {groupByCommunity(query.data).map((group) => (
          <MyCommunityAISection
            key={group.communityId}
            communityId={group.communityId}
            communityName={group.communityName}
            connections={group.connections}
          />
        ))}
      </div>
    );
  };

  return <SettingsSection description={t("memberAI.description")}>{content()}</SettingsSection>;
};
