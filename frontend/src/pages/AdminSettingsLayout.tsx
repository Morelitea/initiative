import { Outlet, Navigate, useLocation, useNavigate } from "react-router-dom";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";

const adminTabs = [
  { value: "auth", label: "Auth", path: "/settings/admin/auth" },
  { value: "branding", label: "Branding", path: "/settings/admin/branding" },
  { value: "email", label: "Email", path: "/settings/admin/email" },
];

export const AdminSettingsLayout = () => {
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const isSuperUser = user?.id === 1;

  if (!isSuperUser) {
    return <Navigate to="/settings/guild" replace />;
  }

  const normalizedPath = location.pathname.replace(/\/+$/, "") || "/";
  const activeTab =
    adminTabs
      .slice()
      .sort((a, b) => b.path.length - a.path.length)
      .find((tab) => normalizedPath === tab.path || normalizedPath.startsWith(`${tab.path}/`))
      ?.value ?? "auth";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Platform settings</h1>
        <p className="text-muted-foreground">Manage authentication, branding, and SMTP for the entire app.</p>
      </div>
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          const tab = adminTabs.find((item) => item.value === value);
          if (tab) {
            navigate(tab.path);
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
