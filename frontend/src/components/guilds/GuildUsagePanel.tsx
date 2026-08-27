import { useTranslation } from "react-i18next";

import { useReadStorageUsageApiV1GGuildIdStorageUsageGet } from "@/api/generated/storage/storage";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useGuilds } from "@/hooks/useGuilds";
import { formatBytes } from "@/lib/fileUtils";

/** Percentage 0–100 of `used` against a cap, or null when the cap is
 * unlimited (null) — a null ratio renders no progress bar. */
const ratioPct = (used: number, max: number | null): number | null =>
  max && max > 0 ? Math.min(100, Math.round((used / max) * 100)) : null;

/** Guild usage against its storage and member caps.
 *
 * Guild admins only, and doubly so: it lives on the admin-gated guild settings
 * page, and the numbers it renders are the administration half of `GuildRead`
 * (caps, plan label), which the API sends to admins alone — as does the
 * storage-usage endpoint below. */
export const GuildUsagePanel = () => {
  const { t } = useTranslation(["guilds", "common"]);
  const { activeGuild } = useGuilds();
  const { billing, openPortal } = useBillingPortal();

  const guildId = activeGuild?.id;
  const { data: usage } = useReadStorageUsageApiV1GGuildIdStorageUsageGet(guildId ?? 0, {
    query: { enabled: guildId != null },
  });

  if (!activeGuild) {
    return null;
  }

  const usedBytes = usage?.usage_bytes ?? 0;
  const maxBytes = activeGuild.max_storage_bytes; // null = unlimited
  const members = activeGuild.member_count;
  const maxUsers = activeGuild.max_users; // null = unlimited
  const storagePct = ratioPct(usedBytes, maxBytes);
  const memberPct = ratioPct(members, maxUsers);
  const tierLabel = activeGuild.tier_name ?? t("usagePanel.selfHosted");

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
              {maxBytes == null
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

        {billing && (
          <>
            <Separator />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm">
                <span className="text-muted-foreground">{t("usagePanel.currentPlan")} </span>
                <span className="font-semibold">{tierLabel}</span>
              </p>
              <div className="flex gap-2">
                <Button size="sm" onClick={() => void openPortal(activeGuild.id, "upgrade")}>
                  {t("usagePanel.upgrade")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void openPortal(activeGuild.id, "manage")}
                >
                  {t("usagePanel.manageBilling")}
                </Button>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
};
