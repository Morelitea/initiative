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
      <Navigate
        to={canManagePlatformConfig(user) ? "/settings/platform" : "/settings/guild"}
        replace
      />
    );
  }

  const normalizedPath = location.pathname.replace(/\/+$/, "") || "/";
  const activeTab =
    [...tabs]
      .sort((a, b) => b.path.length - a.path.length)
      .find((tab) => normalizedPath === tab.path || normalizedPath.startsWith(`${tab.path}/`))
      ?.value ??
    tabs[0]?.value ??
    "users";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-semibold text-3xl tracking-tight">{t("adminDashboard.title")}</h1>
        <p className="text-muted-foreground">{t("adminDashboard.subtitle")}</p>
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
