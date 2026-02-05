import { useMemo } from "react";
import { Outlet, useLocation, useRouter, useParams } from "@tanstack/react-router";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useGuilds } from "@/hooks/useGuilds";
import { guildPath, extractSubPath, isGuildScopedPath } from "@/lib/guildUrl";

export const GuildSettingsLayout = () => {
  const { activeGuild, activeGuildId } = useGuilds();
  const isGuildAdmin = activeGuild?.role === "admin";
  const location = useLocation();
  const router = useRouter();
  const params = useParams({ strict: false }) as { guildId?: string };

  // Get guild ID from URL params or active guild
  const urlGuildId = params.guildId ? Number(params.guildId) : activeGuildId;

  // Define tabs with guild-scoped paths
  const guildSettingsTabs = useMemo(
    () => [
      {
        value: "guild",
        label: "Guild",
        path: urlGuildId ? guildPath(urlGuildId, "/settings") : "/settings",
      },
      {
        value: "ai",
        label: "AI",
        path: urlGuildId ? guildPath(urlGuildId, "/settings/ai") : "/settings/ai",
      },
      {
        value: "users",
        label: "Users",
        path: urlGuildId ? guildPath(urlGuildId, "/settings/users") : "/settings/users",
      },
    ],
    [urlGuildId]
  );

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

  // Normalize path for tab matching
  const currentPath = location.pathname;
  const normalizedPath = isGuildScopedPath(currentPath)
    ? extractSubPath(currentPath).replace(/\/+$/, "") || "/"
    : currentPath.replace(/\/+$/, "") || "/";

  // Map normalized sub-paths to tab values
  const tabSubPaths = [
    { value: "guild", subPath: "/settings" },
    { value: "ai", subPath: "/settings/ai" },
    { value: "users", subPath: "/settings/users" },
  ];

  const activeTab =
    [...tabSubPaths]
      .sort((a, b) => b.subPath.length - a.subPath.length)
      .find((tab) => normalizedPath === tab.subPath || normalizedPath.startsWith(`${tab.subPath}/`))
      ?.value ??
    availableTabs[0]?.value ??
    "guild";

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
            router.navigate({ to: tab.path });
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
