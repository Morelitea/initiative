import { useEffect } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { Tabs, TabsList, TabsTrigger } from "../components/ui/tabs";
import { useAuth } from "../hooks/useAuth";

const settingsTabs = [
  { value: "users", label: "Users", path: "/settings" },
  { value: "initiatives", label: "Initiatives", path: "/settings/initiatives" },
  { value: "auth", label: "Auth", path: "/settings/auth" },
  { value: "api-keys", label: "API Keys", path: "/settings/api-keys" },
  { value: "branding", label: "Branding", path: "/settings/branding" },
  { value: "email", label: "Email", path: "/settings/email" },
];

export const SettingsLayout = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const managesInitiatives =
    user?.initiative_roles?.some((assignment) => assignment.role === "project_manager") ?? false;
  const location = useLocation();
  const navigate = useNavigate();
  const canViewInitiatives = isAdmin || managesInitiatives;
  const availableTabs = isAdmin
    ? settingsTabs
    : settingsTabs.filter((tab) => tab.value === "initiatives");

  useEffect(() => {
    if (!isAdmin && managesInitiatives) {
      const normalizedPath = location.pathname.replace(/\/+$/, "") || "/";
      const isInitiativesRoute =
        normalizedPath === "/settings/initiatives" ||
        normalizedPath.startsWith("/settings/initiatives/");
      if (!isInitiativesRoute) {
        navigate("/settings/initiatives", { replace: true });
      }
    }
  }, [isAdmin, managesInitiatives, location.pathname, navigate]);

  if (!canViewInitiatives) {
    return (
      <div className="space-y-4">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          You need additional permissions to view this page.
        </p>
      </div>
    );
  }

  const normalizedPath = location.pathname.replace(/\/+$/, "") || "/";
  const tabsBySpecificity = [...availableTabs].sort((a, b) => b.path.length - a.path.length);
  const activeTab =
    tabsBySpecificity.find(
      (tab) => normalizedPath === tab.path || normalizedPath.startsWith(`${tab.path}/`)
    )?.value ??
    availableTabs[0]?.value ??
    "initiatives";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Manage workspace access, initiatives, and authentication.
        </p>
      </div>
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          const tab = settingsTabs.find((item) => item.value === value);
          if (tab) {
            navigate(tab.path);
          }
        }}
      >
        <div className="-mx-4 overflow-x-auto pb-2 md:mx-0 md:overflow-visible">
          <TabsList className="w-full min-w-max justify-start gap-2 px-1 md:min-w-0">
            {availableTabs.map((tab) => (
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
