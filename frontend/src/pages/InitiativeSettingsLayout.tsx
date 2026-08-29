/**
 * The frame around one initiative's settings: who you're configuring, the tab
 * bar, and whichever section the address names.
 *
 * The sections are real routes — `/settings/members` is a place, not a piece of
 * component state — so a manager can link someone straight to the join-request
 * queue, and the back button walks back through the sections they visited. The
 * bar still looks and behaves like tabs; selecting one navigates.
 *
 * Everything that decides whether the settings exist at all lives here: a bad
 * id, an initiative this reader can't see, and the standing to configure it.
 * A section that needs more than that says so itself (see
 * `InitiativeSettingsPermissionRequired`) — the outlet is not a permission.
 */

import { Link, Navigate, Outlet, useLocation, useRouter } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import { extractSubPath, isGuildScopedPath, useGuildPath } from "@/lib/guildUrl";
import { matchActiveTab } from "@/lib/tabs";
import { initiativeRoute } from "@/lib/tools";

export const InitiativeSettingsLayout = () => {
  const { t } = useTranslation(["initiatives", "properties"]);
  const gp = useGuildPath();
  const router = useRouter();
  const location = useLocation();

  const {
    initiativeId,
    hasValidInitiativeId,
    initiative,
    isLoading,
    canManageMembers,
    canDeleteInitiative,
  } = useInitiativeSettings();

  const settingsRoute = `${initiativeRoute(initiativeId)}/settings`;

  const tabs = useMemo(
    () => [
      { value: "details", label: t("settings.detailsTab"), path: gp(settingsRoute) },
      { value: "members", label: t("settings.membersTab"), path: gp(`${settingsRoute}/members`) },
      { value: "roles", label: t("settings.rolesTab"), path: gp(`${settingsRoute}/roles`) },
      {
        value: "properties",
        label: t("properties:manager.title"),
        path: gp(`${settingsRoute}/properties`),
      },
      // Aggregate export is managers+ (the guild-wide variant lives in guild
      // settings, admin-gated). The route refuses it too — this only keeps the
      // bar honest about where the reader can go.
      ...(canManageMembers
        ? [{ value: "export", label: t("settings.exportTab"), path: gp(`${settingsRoute}/export`) }]
        : []),
      { value: "danger", label: t("settings.dangerTab"), path: gp(`${settingsRoute}/danger`) },
    ],
    [t, gp, settingsRoute, canManageMembers]
  );

  if (!hasValidInitiativeId) {
    return <Navigate to={gp("/")} replace />;
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("settings.loadingInitiative")}
      </div>
    );
  }

  if (!initiative) {
    return (
      <div className="space-y-4">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to={gp("/")}>{t("settings.backToInitiatives")}</Link>
        </Button>
        <div className="rounded-lg border p-6">
          <h1 className="font-semibold text-3xl tracking-tight">{t("settings.notFound")}</h1>
          <p className="text-muted-foreground">{t("settings.notFoundDescription")}</p>
        </div>
      </div>
    );
  }

  if (!canManageMembers && !canDeleteInitiative) {
    return (
      <div className="space-y-4">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to={gp(initiativeRoute(initiative.id))}>{t("settings.backToInitiative")}</Link>
        </Button>
        <InitiativeSettingsPermissionRequired />
      </div>
    );
  }

  // The tab paths are guild-prefixed; matching happens on the sub-path, so a
  // guild id in the address never decides which tab is lit.
  const currentPath = location.pathname;
  const normalizedPath = isGuildScopedPath(currentPath)
    ? extractSubPath(currentPath).replace(/\/+$/, "") || "/"
    : currentPath.replace(/\/+$/, "") || "/";
  const activeTab = matchActiveTab(
    tabs.map((tab) => ({ value: tab.value, path: extractSubPath(tab.path) })),
    normalizedPath,
    "details"
  );

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp(initiativeRoute(initiative.id))}>{initiative.name}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{t("settings.breadcrumbSettings")}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">{t("settings.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("settings.subtitle")}</p>
      </div>

      <SettingsTabsNav
        tabs={tabs}
        activeTab={activeTab}
        onNavigate={(path) => router.navigate({ to: path })}
      />
      <Outlet />
    </div>
  );
};
