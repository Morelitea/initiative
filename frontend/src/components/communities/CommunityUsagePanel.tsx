import { useTranslation } from "react-i18next";

import { useReadAppUsage } from "@/api/generated/apps/apps";
import type { AppUsageEntry } from "@/api/generated/initiativeAPI.schemas";
import { useReadStorageUsage } from "@/api/generated/storage/storage";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCommunities } from "@/hooks/useCommunities";
import { formatBytes } from "@/lib/fileUtils";
import { localized } from "@/lib/widgets/widgetMeta";

/** Percentage 0–100 of `used` against a cap, or null when the cap is
 * unlimited (null) — a null ratio renders no progress bar. */
const ratioPct = (used: number, max: number | null): number | null =>
  max && max > 0 ? Math.min(100, Math.round((used / max) * 100)) : null;

/** One installed app's usage: each number it returns, by its own label, read
 *  "320 of 500" when it also returns `<key>_limit` (null there is unlimited). */
const AppUsageSection = ({ entry }: { entry: AppUsageEntry }) => {
  const { t, i18n } = useTranslation(["communities", "common"]);
  const language = i18n.resolvedLanguage ?? i18n.language;
  const keys = new Set((entry.returns ?? []).map((r) => r.key));
  const fmt = (value: unknown) =>
    typeof value === "number" ? value.toLocaleString(language) : null;
  const text = (key: string): string => {
    const values = entry.values;
    if (!values) return t("usagePanel.storageUnavailable");
    const used = fmt(values[key]);
    if (!keys.has(`${key}_limit`)) return used ?? t("usagePanel.storageUnavailable");
    const max = fmt(values[`${key}_limit`]);
    if (max != null && used != null) return t("usagePanel.countOfMax", { used, max });
    if (used != null) return t("usagePanel.countOfUnlimited", { used });
    return t("usagePanel.unlimited");
  };
  const figures = (entry.returns ?? []).filter(
    (r) =>
      r.type === "int" && !r.list && !(r.key.endsWith("_limit") && keys.has(r.key.slice(0, -6)))
  );

  return (
    <div className="space-y-4">
      <h3 className="font-semibold text-muted-foreground text-xs uppercase tracking-wide">
        {entry.name}
      </h3>
      {figures.map((r) => (
        <div key={r.key} className="flex justify-between text-sm">
          <span className="font-medium">{localized(r.label, language) ?? r.key}</span>
          <span className="text-muted-foreground">{text(r.key)}</span>
        </div>
      ))}
    </div>
  );
};

/** Community usage against its storage and member caps, and what its installed
 *  apps report it has used of what they meter.
 *
 * On the seat's Usage tab, the first in community settings, on every install:
 * self-hosted, the caps are the operator's; hosted, they come with the plan,
 * which `CommunityBillingPanel` shows below it. The numbers are the administration
 * half of `CommunityRead`, which the API sends to admins alone — as does the
 * storage-usage endpoint below, and the app-usage one. */
export const CommunityUsagePanel = () => {
  const { t } = useTranslation(["communities", "common"]);
  const { activeCommunity } = useCommunities();
  // The tab is "Usage" alone unless the plan sits beside this card.
  const { billing } = useAppConfig();

  const communityId = activeCommunity?.id;
  // Read on the settings surface, by the same rung as the caps beside it, so a
  // settings grant reaches it too. Until it answers — or if it cannot — the
  // figure is not shown at all: an empty bar would read as nothing stored.
  const { data: usage, isError } = useReadStorageUsage(communityId ?? 0, {
    query: { enabled: communityId != null },
  });
  // Each installed app's own figures, read through Initiative from the app.
  // Nothing renders until it answers; a community with no such app has none.
  const { data: appUsage } = useReadAppUsage(communityId ?? 0, {
    query: { enabled: communityId != null },
  });
  const appEntries = appUsage?.items ?? [];

  if (!activeCommunity) {
    return null;
  }

  const usedBytes = usage?.usage_bytes;
  const maxBytes = activeCommunity.max_storage_bytes; // null = unlimited
  const members = activeCommunity.member_count;
  const maxUsers = activeCommunity.max_users; // null = unlimited
  const storagePct = usedBytes == null ? null : ratioPct(usedBytes, maxBytes);
  const memberPct = ratioPct(members, maxUsers);

  return (
    <Card>
      {billing ? (
        <CardHeader>
          <CardTitle>{t("usagePanel.title")}</CardTitle>
        </CardHeader>
      ) : null}
      <CardContent className={billing ? "space-y-6" : "space-y-6 pt-6"}>
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
                ? t("usagePanel.countOfUnlimited", { used: members })
                : t("usagePanel.countOfMax", { used: members, max: maxUsers })}
            </span>
          </div>
          {memberPct != null && <Progress value={memberPct} />}
        </div>

        {appEntries.map((entry) => (
          <AppUsageSection key={entry.app_id} entry={entry} />
        ))}
      </CardContent>
    </Card>
  );
};
