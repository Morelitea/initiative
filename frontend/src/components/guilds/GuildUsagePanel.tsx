import { useTranslation } from "react-i18next";

import { useReadStorageUsageApiV1CGuildIdStorageUsageGet } from "@/api/generated/storage/storage";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useGuilds } from "@/hooks/useGuilds";
import { formatBytes } from "@/lib/fileUtils";

/** Percentage 0–100 of `used` against a cap, or null when the cap is
 * unlimited (null) — a null ratio renders no progress bar. */
const ratioPct = (used: number, max: number | null): number | null =>
  max && max > 0 ? Math.min(100, Math.round((used / max) * 100)) : null;

/** Guild usage against its storage and member caps.
 *
 * On the seat's Usage tab, the first in community settings, on every install:
 * self-hosted, the caps are the operator's; hosted, they come with the plan,
 * which `GuildBillingPanel` shows below it. The numbers are the administration
 * half of `GuildRead`, which the API sends to admins alone — as does the
 * storage-usage endpoint below. */
export const GuildUsagePanel = () => {
  const { t } = useTranslation(["guilds", "common"]);
  const { activeGuild } = useGuilds();

  const guildId = activeGuild?.id;
  // Read on the settings surface, by the same rung as the caps beside it, so a
  // settings grant reaches it too. Until it answers — or if it cannot — the
  // figure is not shown at all: an empty bar would read as nothing stored.
  const { data: usage, isError } = useReadStorageUsageApiV1CGuildIdStorageUsageGet(guildId ?? 0, {
    query: { enabled: guildId != null },
  });

  if (!activeGuild) {
    return null;
  }

  const usedBytes = usage?.usage_bytes;
  const maxBytes = activeGuild.max_storage_bytes; // null = unlimited
  const members = activeGuild.member_count;
  const maxUsers = activeGuild.max_users; // null = unlimited
  const storagePct = usedBytes == null ? null : ratioPct(usedBytes, maxBytes);
  const memberPct = ratioPct(members, maxUsers);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("usagePanel.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="font-medium">{t("usagePanel.storage")}</span>
            <span className="text-muted-foreground">
              {usedBytes == null
                ? isError
                  ? t("usagePanel.storageUnavailable")
                  : null
                : maxBytes == null
                  ? t("usagePanel.usedOfUnlimited", { used: formatBytes(usedBytes) })
                  : t("usagePanel.usedOfMax", {
                      used: formatBytes(usedBytes),
                      max: formatBytes(maxBytes),
                    })}
            </span>
          </div>
          {storagePct != null && <Progress value={storagePct} />}
        </div>

        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="font-medium">{t("usagePanel.members")}</span>
            <span className="text-muted-foreground">
              {maxUsers == null
                ? t("usagePanel.membersOfUnlimited", { used: members })
                : t("usagePanel.membersOfMax", { used: members, max: maxUsers })}
            </span>
          </div>
          {memberPct != null && <Progress value={memberPct} />}
        </div>
      </CardContent>
    </Card>
  );
};
