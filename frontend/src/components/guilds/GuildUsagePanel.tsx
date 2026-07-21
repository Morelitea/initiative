import { useTranslation } from "react-i18next";

import { createGuildBillingHandoffApiV1GuildsGuildIdBillingHandoffPost } from "@/api/generated/guilds/guilds";
import { useReadStorageUsageApiV1GGuildIdStorageUsageGet } from "@/api/generated/storage/storage";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useGuilds } from "@/hooks/useGuilds";
import { formatBytes } from "@/lib/fileUtils";

/** Percentage 0–100 of `used` against a cap, or null when the cap is
 * unlimited (null) — a null ratio renders no progress bar. */
const ratioPct = (used: number, max: number | null): number | null =>
  max && max > 0 ? Math.min(100, Math.round((used / max) * 100)) : null;

/** Guild usage against its storage and member caps. */
export const GuildUsagePanel = () => {
  const { t, i18n } = useTranslation(["guilds", "common"]);
  const { activeGuild } = useGuilds();
  const { billing } = useAppConfig();

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

  const lang = i18n.resolvedLanguage ?? i18n.language;
  const isAdmin = activeGuild.role === "admin";
  const anonUpgradeUrl = billing
    ? `${billing.url}/upgrade?guild=${activeGuild.id}&lang=${encodeURIComponent(lang)}`
    : null;

  const openPortal = async (page: "manage" | "upgrade") => {
    if (!billing) return;
    const base = `${billing.url}/${page}?guild=${activeGuild.id}&lang=${encodeURIComponent(lang)}`;
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    try {
      const { handoff_token } = await createGuildBillingHandoffApiV1GuildsGuildIdBillingHandoffPost(
        activeGuild.id
      );
      const url = `${base}#handoff=${encodeURIComponent(handoff_token)}`;
      if (tab) tab.location.href = url;
      else window.open(url, "_blank", "noopener,noreferrer");
    } catch {
      if (tab) tab.location.href = base;
      else window.open(base, "_blank", "noopener,noreferrer");
    }
  };

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
                {isAdmin ? (
                  <>
                    <Button size="sm" onClick={() => openPortal("upgrade")}>
                      {t("usagePanel.upgrade")}
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => openPortal("manage")}>
                      {t("usagePanel.manageBilling")}
                    </Button>
                  </>
                ) : (
                  <Button asChild size="sm">
                    <a href={anonUpgradeUrl ?? "#"} target="_blank" rel="noopener noreferrer">
                      {t("usagePanel.upgrade")}
                    </a>
                  </Button>
                )}
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
};
