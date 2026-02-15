import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Outlet, Navigate, useLocation, useRouter } from "@tanstack/react-router";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";

export const AdminSettingsLayout = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const location = useLocation();
  const router = useRouter();
  const isPlatformAdmin = user?.role === "admin";

  const adminTabs = useMemo(
    () => [
      { value: "auth", label: t("adminLayout.tabs.auth"), path: "/settings/admin/auth" },
      {
        value: "branding",
        label: t("adminLayout.tabs.branding"),
        path: "/settings/admin/branding",
      },
      { value: "email", label: t("adminLayout.tabs.email"), path: "/settings/admin/email" },
      { value: "ai", label: t("adminLayout.tabs.ai"), path: "/settings/admin/ai" },
      { value: "users", label: t("adminLayout.tabs.users"), path: "/settings/admin/users" },
    ],
    [t]
  );

  if (!isPlatformAdmin) {
    return <Navigate to="/settings/guild" replace />;
  }

  const normalizedPath = location.pathname.replace(/\/+$/, "") || "/";
  const activeTab =
    [...adminTabs]
      .sort((a, b) => b.path.length - a.path.length)
      .find((tab) => normalizedPath === tab.path || normalizedPath.startsWith(`${tab.path}/`))
      ?.value ?? "auth";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t("adminLayout.title")}</h1>
        <p className="text-muted-foreground">{t("adminLayout.subtitle")}</p>
      </div>
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          const tab = adminTabs.find((item) => item.value === value);
          if (tab) {
            router.navigate({ to: tab.path });
          }
        }}
      >
        <div className="-mx-4 overflow-x-auto pb-2 md:mx-0 md:overflow-visible">
          <TabsList className="w-full min-w-max justify-start gap-2 px-1 md:min-w-0">
            {adminTabs.map((tab) => (
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
