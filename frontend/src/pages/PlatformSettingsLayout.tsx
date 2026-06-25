import { Navigate, Outlet, useLocation, useRouter } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import {
  Capability,
  canAccessAdminDashboard,
  canManagePlatformConfig,
  hasCapability,
} from "@/lib/permissions";

/**
 * App-wide *configuration* area: authentication, branding, email, and AI.
 * Owner-only (`config.manage`). Operational tools (users, access) live in the
 * separate Admin dashboard.
 */
export const PlatformSettingsLayout = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const location = useLocation();
  const router = useRouter();

  const tabs = useMemo(() => {
    const all = [
      { value: "auth", label: t("platformLayout.tabs.auth"), path: "/settings/platform/auth" },
      {
        value: "branding",
        label: t("platformLayout.tabs.branding"),
        path: "/settings/platform/branding",
      },
      { value: "email", label: t("platformLayout.tabs.email"), path: "/settings/platform/email" },
      { value: "ai", label: t("platformLayout.tabs.ai"), path: "/settings/platform/ai" },
    ];
    return hasCapability(user, Capability.configManage) ? all : [];
  }, [t, user]);

  if (!canManagePlatformConfig(user)) {
    // Send operational staff to their dashboard; everyone else to guild settings.
    return (
      <Navigate
        to={canAccessAdminDashboard(user) ? "/settings/admin" : "/settings/guild"}
        replace
      />
    );
  }

  const normalizedPath = location.pathname.replace(/\/+$/, "") || "/";
  const activeTab =
    [...tabs]
      .sort((a, b) => b.path.length - a.path.length)
      .find((tab) => normalizedPath === tab.path || normalizedPath.startsWith(`${tab.path}/`))
      ?.value ?? "auth";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-semibold text-3xl tracking-tight">{t("platformLayout.title")}</h1>
        <p className="text-muted-foreground">{t("platformLayout.subtitle")}</p>
      </div>
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          const tab = tabs.find((item) => item.value === value);
          if (tab) {
            router.navigate({ to: tab.path });
          }
        }}
      >
        <div className="-mx-4 overflow-x-auto pb-2 md:mx-0 md:overflow-visible">
          <TabsList className="w-full min-w-max justify-start gap-2 px-1 md:min-w-0">
            {tabs.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value} className="shrink-0">
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
      </Tabs>
      <Outlet />
    </div>
  );
};
