import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";

const userSettingsTabs = [
  { value: "profile", label: "Profile", path: "/profile" },
  { value: "interface", label: "Interface", path: "/profile/interface" },
  { value: "notifications", label: "Notifications", path: "/profile/notifications" },
  { value: "danger", label: "Danger Zone", path: "/profile/danger" },
];

export const UserSettingsLayout = () => {
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  if (!user) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">You need to be logged in to manage your profile.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/login">Go to login</Link>
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
        <h1 className="text-3xl font-semibold tracking-tight">User settings</h1>
        <p className="text-muted-foreground text-sm">
          Manage your profile, interface preferences, and notifications.
        </p>
      </div>
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          const tab = userSettingsTabs.find((item) => item.value === value);
          if (tab) {
            navigate(tab.path);
          }
        }}
      >
        <div className="-mx-4 overflow-x-auto pb-2 md:mx-0 md:overflow-visible">
          <TabsList className="w-full min-w-max justify-start gap-2 px-1 md:min-w-0">
            {userSettingsTabs.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value} className="shrink-0">
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <Outlet />
      </Tabs>
    </div>
  );
};
