import { Outlet, useLocation, useRouter } from "@tanstack/react-router";
import { type ReactNode, Suspense, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import { SettingsPaneSkeleton } from "@/components/skeletons/PageSkeletons";
import { Badge } from "@/components/ui/badge";
import { useGuildBillingSummary } from "@/hooks/useGuildBillingSummary";
import { useGuildSettingsTabs } from "@/hooks/useGuildSettingsTabs";
import { useGuilds } from "@/hooks/useGuilds";
import { trialDaysLeft } from "@/lib/billingSummary";
import { extractSubPath, isGuildScopedPath } from "@/lib/guildUrl";
import { matchActiveTab } from "@/lib/tabs";

export const GuildSettingsLayout = () => {
  const { t } = useTranslation(["settings"]);
  const { activeGuild } = useGuilds();
  // Running the community: held as its admin, or lent by a settings grant at
  // either rung.
  const administers = Boolean(activeGuild?.can.administer);
  // Whether what the rung reaches may also be changed — the server's answer.
  // Without it every control on these pages is shown disabled.
  const changesSettings = Boolean(activeGuild?.can.configure);
  const location = useLocation();
  const router = useRouter();
  const tabs = useGuildSettingsTabs();

  // The Usage tab says when the plan wants a look: a failed payment, or a
  // trial running out. Hosted only — the query never runs without a portal —
  // and the query the tab's own panel reads, so opening it is one request.
  const { data: summary } = useGuildBillingSummary(activeGuild);
  const guildSettingsTabs = useMemo(() => {
    let usageMark: ReactNode = null;
    const daysLeft = trialDaysLeft(summary);
    if (summary?.available && summary.payment_failed) {
      const label = t("guildLayout.tabBadge.paymentFailed");
      usageMark = (
        <span
          role="img"
          aria-label={label}
          title={label}
          className="h-2 w-2 rounded-full bg-destructive"
        />
      );
    } else if (daysLeft != null) {
      usageMark = (
        <Badge variant="secondary" className="px-1.5 py-0 font-medium">
          {daysLeft === 0
            ? t("guildLayout.tabBadge.trialLastDay")
            : t("guildLayout.tabBadge.trial", { count: daysLeft })}
        </Badge>
      );
    }
    return usageMark
      ? tabs.map((tab) => (tab.value === "usage" ? { ...tab, adornment: usageMark } : tab))
      : tabs;
  }, [tabs, summary, t]);

  const canViewSettings = administers;

  if (!canViewSettings) {
    return (
      <div className="space-y-4">
        <h1 className="font-semibold text-3xl tracking-tight">{t("guildLayout.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("guildLayout.permissionDenied")}</p>
      </div>
    );
  }

  // Normalize path for tab matching
  const currentPath = location.pathname;
  const normalizedPath = isGuildScopedPath(currentPath)
    ? extractSubPath(currentPath).replace(/\/+$/, "") || "/"
    : currentPath.replace(/\/+$/, "") || "/";

  // Derived from the tabs themselves rather than restated: a second hand-kept
  // list is a tab that highlights the wrong one the day someone adds a tab and
  // updates only the list they happened to be looking at. The tab paths are
  // guild-prefixed; matching happens on the sub-path.
  const tabSubPaths = guildSettingsTabs.map((tab) => ({
    value: tab.value,
    path: extractSubPath(tab.path),
  }));

  const activeTab = matchActiveTab(
    tabSubPaths,
    normalizedPath,
    guildSettingsTabs[0]?.value ?? "guild"
  );

  // A read-only guild shows the admin a prominent notice pointing them to the
  // platform operator (the status reaches admins only — see the backend
  // GuildRead serialization). A suspended one never reaches settings at all.
  const statusNotice =
    activeGuild?.status === "read_only"
      ? {
          label: t("guildLayout.restricted.read_only.label"),
          message: t("guildLayout.restricted.read_only.message"),
        }
      : null;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-semibold text-3xl tracking-tight">{t("guildLayout.title")}</h1>
          {statusNotice && <Badge variant="destructive">{statusNotice.label}</Badge>}
        </div>
        {statusNotice && (
          <p className="font-bold text-destructive text-sm">{statusNotice.message}</p>
        )}
        {!changesSettings && (
          <p className="text-muted-foreground text-sm">{t("guildLayout.viewOnly")}</p>
        )}
      </div>
      <SettingsTabsNav
        tabs={guildSettingsTabs}
        activeTab={activeTab}
        onNavigate={(path) => router.navigate({ to: path })}
      />
      <fieldset disabled={!changesSettings} className="m-0 min-w-0 border-0 p-0">
        <Suspense fallback={<SettingsPaneSkeleton />}>
          <Outlet />
        </Suspense>
      </fieldset>
    </div>
  );
};
