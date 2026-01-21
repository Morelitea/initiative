import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";

const guildSettingsTabs = [
  { value: "guild", label: "Guild", path: "/settings/guild" },
  { value: "ai", label: "AI", path: "/settings/guild/ai" },
  { value: "users", label: "Users", path: "/settings/guild/users" },
];

export const GuildSettingsLayout = () => {
  const { user } = useAuth();
  const { activeGuild } = useGuilds();
  const isGuildAdmin = user?.role === "admin" || activeGuild?.role === "admin";
  const location = useLocation();
  const navigate = useNavigate();

  const canViewSettings = isGuildAdmin;
  const availableTabs = isGuildAdmin ? guildSettingsTabs : [];

  if (!canViewSettings) {
    return (
      <div className="space-y-4">
        <h1 className="text-3xl font-semibold tracking-tight">Guild settings</h1>
        <p className="text-muted-foreground text-sm">
          You need additional permissions to view this page.
        </p>
      </div>
    );
  }

  const normalizedPath = location.pathname.replace(/\/+$/, "") || "/";
  const activeTab =
    availableTabs
      .slice()
      .sort((a, b) => b.path.length - a.path.length)
      .find((tab) => normalizedPath === tab.path || normalizedPath.startsWith(`${tab.path}/`))
      ?.value ??
    availableTabs[0]?.value ??
    "users";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Guild settings</h1>
        <p className="text-muted-foreground">Manage workspace membership and guild details.</p>
      </div>
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          const tab = guildSettingsTabs.find((item) => item.value === value);
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
