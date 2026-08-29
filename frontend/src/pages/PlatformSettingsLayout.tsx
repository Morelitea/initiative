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
 * App-wide *configuration* area: authentication, branding, email, AI, storage,
 * and app service registrations. Owner-only (`config.manage` / `apps.manage`).
 * Operational tools (users, access) live in the separate Admin dashboard.
 */
export const PlatformSettingsLayout = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const location = useLocation();
  const router = useRouter();

  const tabs = useMemo(() => {
    // Two capabilities reach this area: `config.manage` owns app-wide
    // configuration, `apps.manage` owns app service registrations. A holder of
    // one shouldn't be shown the other's tabs.
    const configTabs = [
      { value: "auth", label: t("platformLayout.tabs.auth"), path: "/settings/platform/auth" },
      {
        value: "branding",
        label: t("platformLayout.tabs.branding"),
        path: "/settings/platform/branding",
      },
      { value: "email", label: t("platformLayout.tabs.email"), path: "/settings/platform/email" },
      {
        value: "community",
        label: t("platformLayout.tabs.community"),
        path: "/settings/platform/community",
      },
      { value: "ai", label: t("platformLayout.tabs.ai"), path: "/settings/platform/ai" },
      {
        value: "storage",
        label: t("platformLayout.tabs.storage"),
        path: "/settings/platform/storage",
      },
    ];
    const appTabs = [
      {
        value: "app-services",
        label: t("platformLayout.tabs.appServices"),
        path: "/settings/platform/app-services",
      },
    ];
    return [
      ...(hasCapability(user, Capability.configManage) ? configTabs : []),
      ...(hasCapability(user, Capability.appsManage) ? appTabs : []),
    ];
  }, [t, user]);

  if (!canManagePlatformConfig(user)) {
    // Send operational staff to their dashboard; everyone else to guild settings.
    return (
      <Navigate to={canAccessAdminDashboard(user) ? "/settings/admin" : "/settings"} replace />
    );
  }

  const normalizedPath = location.pathname.replace(/\/+$/, "") || "/";
  // Fall back to whichever tab this user actually has, not always `auth`.
  const activeTab = matchActiveTab(tabs, normalizedPath, tabs[0]?.value ?? "auth");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-semibold text-3xl tracking-tight">{t("platformLayout.title")}</h1>
        <p className="text-muted-foreground">{t("platformLayout.subtitle")}</p>
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
