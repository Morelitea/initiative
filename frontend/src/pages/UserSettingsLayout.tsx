import { Link, Outlet, useLocation, useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";

const userSettingsTabs = [
  { value: "profile", labelKey: "layout.tabs.profile", path: "/profile" },
  { value: "interface", labelKey: "layout.tabs.interface", path: "/profile/interface" },
  { value: "notifications", labelKey: "layout.tabs.notifications", path: "/profile/notifications" },
  { value: "ai", labelKey: "layout.tabs.ai", path: "/profile/ai" },
  { value: "import", labelKey: "layout.tabs.import", path: "/profile/import" },
  { value: "security", labelKey: "layout.tabs.security", path: "/profile/security" },
  { value: "danger", labelKey: "layout.tabs.danger", path: "/profile/danger" },
] as const;

export const UserSettingsLayout = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const location = useLocation();
  const router = useRouter();

  if (!user) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">{t("layout.loginRequired")}</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/login">{t("layout.goToLogin")}</Link>
        </Button>
      </div>
    );
  }

  const normalizedPath = location.pathname.replace(/\/+$/, "") || "/";
  const tabsBySpecificity = [...userSettingsTabs].sort((a, b) => b.path.length - a.path.length);
  const activeTab =
    tabsBySpecificity.find(
      (tab) => normalizedPath === tab.path || normalizedPath.startsWith(`${tab.path}/`)
    )?.value ?? "registration";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t("layout.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("layout.subtitle")}</p>
      </div>
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          const tab = userSettingsTabs.find((item) => item.value === value);
          if (tab) {
            router.navigate({ to: tab.path });
          }
        }}
      >
        <div className="-mx-4 overflow-x-auto pb-2 md:mx-0 md:overflow-visible">
          <TabsList className="w-full min-w-max justify-start gap-2 px-1 md:min-w-0">
            {userSettingsTabs.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value} className="shrink-0">
                {t(tab.labelKey)}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <Outlet />
      </Tabs>
    </div>
  );
};
