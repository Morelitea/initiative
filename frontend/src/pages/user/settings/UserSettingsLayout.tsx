import { Link, Outlet, useLocation, useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { matchActiveTab } from "@/lib/tabs";

const userSettingsTabs = [
  { value: "profile", labelKey: "layout.tabs.profile", path: "/profile" },
  { value: "interface", labelKey: "layout.tabs.interface", path: "/profile/interface" },
  { value: "notifications", labelKey: "layout.tabs.notifications", path: "/profile/notifications" },
  { value: "ai", labelKey: "layout.tabs.ai", path: "/profile/ai" },
  { value: "import", labelKey: "layout.tabs.import", path: "/profile/import" },
  { value: "security", labelKey: "layout.tabs.security", path: "/profile/security" },
  { value: "trash", labelKey: "layout.tabs.trash", path: "/profile/trash" },
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

  const tabs = userSettingsTabs.map((tab) => ({
    value: tab.value,
    label: t(tab.labelKey),
    path: tab.path,
  }));
  const normalizedPath = location.pathname.replace(/\/+$/, "") || "/";
  const activeTab = matchActiveTab(tabs, normalizedPath, "registration");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-semibold text-3xl tracking-tight">{t("layout.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("layout.subtitle")}</p>
      </div>
      <SettingsTabsNav
        tabs={tabs}
        activeTab={activeTab}
        onNavigate={(path) => router.navigate({ to: path })}
      >
        <Outlet />
      </SettingsTabsNav>
    </div>
  );
};
