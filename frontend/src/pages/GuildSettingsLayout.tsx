import { Outlet, useLocation, useParams, useRouter } from "@tanstack/react-router";
import { Suspense, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import { SettingsPaneSkeleton } from "@/components/skeletons/PageSkeletons";
import { Badge } from "@/components/ui/badge";
import { useGuilds } from "@/hooks/useGuilds";
import { extractSubPath, guildPath, isGuildScopedPath } from "@/lib/guildUrl";
import {
  administersGuild,
  changesGuildSettings,
  holdsGuildSeat,
  reachesGuildContent,
} from "@/lib/permissions";
import { matchActiveTab } from "@/lib/tabs";

export const GuildSettingsLayout = () => {
  const { t } = useTranslation(["settings"]);
  const { activeGuild, activeGuildId } = useGuilds();
  // Running the community: held as its admin, or lent by a settings grant at
  // either rung. Separate from reaching the work inside it, which a settings
  // grant does not — the tabs built on content are dropped below rather than
  // rendered into refusals.
  const administers = administersGuild(activeGuild);
  // Whether what the rung reaches may also be changed — the server's answer.
  // Without it every control on these pages is shown disabled.
  const changesSettings = changesGuildSettings(activeGuild);
  const reachesContent = reachesGuildContent(activeGuild);
  // The seat above admin, which holds this community's sign-in and its
  // integrations — held outright, or lent for a window by a settings grant.
  const onTheGrantedSeat = activeGuild?.grantSettingsLevel === "superadmin";
  const isSuperadmin = holdsGuildSeat(activeGuild);
  // Where the community has a sign-in of its own to configure, that is. Most
  // never do: the operator grants each half of the surface separately, and
  // with neither there is nothing on the tab to show anybody. A grantee's
  // entry carries no options — the page reads the real ones and shows nothing
  // where there are none.
  const authOptions = activeGuild?.auth_options ?? [];
  const configuresItsOwnSignIn =
    isSuperadmin &&
    (onTheGrantedSeat || authOptions.includes("providers") || authOptions.includes("restrictions"));
  const location = useLocation();
  const router = useRouter();
  const params = useParams({ strict: false }) as { guildId?: string };
  // Get guild ID from URL params or active guild
  const urlGuildId = params.guildId ? Number(params.guildId) : activeGuildId;

  // Define tabs with guild-scoped paths
  const guildSettingsTabs = useMemo(() => {
    const tabs = [
      {
        value: "guild",
        label: t("guildLayout.tabs.guild"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings") : "/settings",
      },
      {
        value: "users",
        label: t("guildLayout.tabs.users"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings/users") : "/settings/users",
      },
      ...(configuresItsOwnSignIn
        ? [
            {
              // Everything on this tab is the superadmin's to set, so the
              // tab is theirs too — an ordinary admin has nothing to do on it.
              value: "security",
              label: t("guildLayout.tabs.security"),
              path: urlGuildId ? guildPath(urlGuildId, "/settings/security") : "/settings/security",
            },
          ]
        : []),
      ...(reachesContent
        ? [
            {
              value: "initiatives",
              label: t("guildLayout.tabs.initiatives"),
              path: urlGuildId
                ? guildPath(urlGuildId, "/settings/initiatives")
                : "/settings/initiatives",
            },
          ]
        : []),
      // What the community hands to somebody outside it — an AI provider, an
      // app — is the seat's to decide, the way its sign-in is. An ordinary
      // admin runs the community; these say who else gets to see it.
      ...(isSuperadmin
        ? [
            {
              value: "integrations",
              label: t("guildLayout.tabs.integrations"),
              path: urlGuildId
                ? guildPath(urlGuildId, "/settings/integrations")
                : "/settings/integrations",
            },
          ]
        : []),
      ...(reachesContent
        ? [
            {
              value: "trash",
              label: t("guildLayout.tabs.trash"),
              path: urlGuildId ? guildPath(urlGuildId, "/settings/trash") : "/settings/trash",
            },
          ]
        : []),
      // Taking the community's every initiative out in one file, or putting
      // one back, reaches as far as deleting it does — so it sits with the
      // same seat. An ordinary admin runs the community; this one moves it.
      ...(isSuperadmin
        ? [
            {
              value: "data",
              label: t("guildLayout.tabs.data"),
              path: urlGuildId ? guildPath(urlGuildId, "/settings/data") : "/settings/data",
            },
          ]
        : []),
    ];
    // Danger zone lives last — destructive guild deletion is deliberately
    // tucked behind its own tab rather than the first screen — and only the
    // seat sees it. Deleting a community is the one action an admin could not
    // undo and could not have undone for them; it belongs with the seat a
    // restore needs, which is also the seat the receipt is written to.
    if (isSuperadmin) {
      tabs.push({
        value: "danger-zone",
        label: t("guildLayout.tabs.dangerZone"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings/danger-zone") : "/settings/danger-zone",
      });
    }
    return tabs;
  }, [urlGuildId, t, configuresItsOwnSignIn, isSuperadmin, reachesContent]);

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
        <p className="text-muted-foreground">{t("guildLayout.subtitle")}</p>
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
