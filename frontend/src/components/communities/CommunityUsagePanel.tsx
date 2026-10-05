import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { useReadAppUsage } from "@/api/generated/apps/apps";
import type { AppUsageEntry, AppUsageFigure } from "@/api/generated/initiativeAPI.schemas";
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

/** What one figure an app reported reads as: a count against its limit, a
 *  count with no limit, or unlimited. */
const figureText = (
  figure: AppUsageFigure,
  formatCount: (value: number) => string,
  t: TFunction<["communities", "common"]>
): string => {
  const value = figure.value ?? null;
  if (figure.limited && figure.limit == null) {
    return value == null
      ? t("usagePanel.unlimited")
      : t("usagePanel.countOfUnlimited", { used: formatCount(value) });
  }
  if (value == null) {
    return t("usagePanel.storageUnavailable");
  }
  if (figure.limited && figure.limit != null) {
    return t("usagePanel.countOfMax", { used: formatCount(value), max: formatCount(figure.limit) });
  }
  return formatCount(value);
};

/** One installed app's figures: runs, credits, whatever it meters. The labels
 *  are the app's own, in every language it supplied. */
const AppUsageSection = ({ entry }: { entry: AppUsageEntry }) => {
  const { t, i18n } = useTranslation(["communities", "common"]);
  const language = i18n.resolvedLanguage ?? i18n.language;
  const formatCount = (value: number) => value.toLocaleString(language);

  return (
    <div className="space-y-4">
      <h3 className="font-semibold text-muted-foreground text-xs uppercase tracking-wide">
        {entry.name}
      </h3>
      {(entry.figures ?? []).map((figure) => {
        const pct =
          entry.available !== false && figure.limited && figure.value != null
            ? ratioPct(figure.value, figure.limit ?? null)
            : null;
        return (
          <div key={figure.key} className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="font-medium">{localized(figure.label, language) ?? figure.key}</span>
              <span className="text-muted-foreground">
                {entry.available === false
                  ? t("usagePanel.storageUnavailable")
                  : figureText(figure, formatCount, t)}
              </span>
            </div>
            {pct != null && <Progress value={pct} />}
          </div>
        );
      })}
    </div>
  );
};

/** Community usage against its storage and seat caps, and what its installed
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
            <span className="font-medium">{t("usagePanel.seats")}</span>
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
