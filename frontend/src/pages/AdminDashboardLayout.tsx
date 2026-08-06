import { Navigate, Outlet, useLocation, useRouter } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import { useAuth } from "@/hooks/useAuth";
import {
  Capability,
  canAccessAdminDashboard,
  canManagePlatformConfig,
  hasCapability,
} from "@/lib/permissions";
import { matchActiveTab } from "@/lib/tabs";

/**
 * Operational admin area: platform users and time-bound access grants.
 * Reachable by support/moderator/operator/owner depending on capability.
 * App-wide *configuration* lives in the separate Platform settings area.
 */
export const AdminDashboardLayout = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const location = useLocation();
  const router = useRouter();

  const tabs = useMemo(() => {
    // Each tab is visible if the user holds ANY of its capabilities.
    const all: { value: string; label: string; path: string; capabilities: Capability[] }[] = [
      {
        value: "users",
        label: t("adminDashboard.tabs.users"),
        path: "/settings/admin/users",
        capabilities: [Capability.usersRead],
      },
      {
        value: "guilds",
        label: t("adminDashboard.tabs.guilds"),
        path: "/settings/admin/guilds",
        capabilities: [Capability.guildsManage],
      },
      {
        value: "access",
        label: t("adminDashboard.tabs.access"),
        path: "/settings/admin/access",
        capabilities: [Capability.accessRequest, Capability.accessApprove],
      },
    ];
    return all.filter((tab) => tab.capabilities.some((c) => hasCapability(user, c)));
  }, [t, user]);

  if (!canAccessAdminDashboard(user)) {
    return (
      <Navigate to={canManagePlatformConfig(user) ? "/settings/platform" : "/settings"} replace />
    );
  }

  const normalizedPath = location.pathname.replace(/\/+$/, "") || "/";
  const activeTab = matchActiveTab(tabs, normalizedPath, tabs[0]?.value ?? "users");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-semibold text-3xl tracking-tight">{t("adminDashboard.title")}</h1>
        <p className="text-muted-foreground">{t("adminDashboard.subtitle")}</p>
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
