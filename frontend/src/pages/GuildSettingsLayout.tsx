import { Outlet, useLocation, useParams, useRouter } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useGuilds } from "@/hooks/useGuilds";
import { extractSubPath, guildPath, isGuildScopedPath } from "@/lib/guildUrl";

export const GuildSettingsLayout = () => {
  const { t } = useTranslation(["settings"]);
  const { activeGuild, activeGuildId } = useGuilds();
  const isGuildAdmin = activeGuild?.role === "admin";
  const location = useLocation();
  const router = useRouter();
  const params = useParams({ strict: false }) as { guildId?: string };
  // Surface the Automations tab only when the deployment has an advanced
  // tool URL configured; OSS instances without it never see this tab even
  // if a user is a guild admin.
  const { advancedTool } = useAppConfig();

  // Get guild ID from URL params or active guild
  const urlGuildId = params.guildId ? Number(params.guildId) : activeGuildId;

  // Define tabs with guild-scoped paths
  const guildSettingsTabs = useMemo(() => {
    const tabs = [
      {
        value: "guild",
        label: t("guildLayout.tabs.guild"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings") : "/settings",
      },
      {
        value: "ai",
        label: t("guildLayout.tabs.ai"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings/ai") : "/settings/ai",
      },
      {
        value: "users",
        label: t("guildLayout.tabs.users"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings/users") : "/settings/users",
      },
      {
        value: "auth",
        label: t("guildLayout.tabs.auth"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings/auth") : "/settings/auth",
      },
      {
        value: "initiatives",
        label: t("guildLayout.tabs.initiatives"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings/initiatives") : "/settings/initiatives",
      },
      {
        value: "trash",
        label: t("guildLayout.tabs.trash"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings/trash") : "/settings/trash",
      },
      {
        value: "data",
        label: t("guildLayout.tabs.data"),
        path: urlGuildId ? guildPath(urlGuildId, "/settings/data") : "/settings/data",
      },
    ];
    if (advancedTool) {
      tabs.push({
        value: "advanced-tool",
        // The configured runtime name (e.g. "Automations") is what the
        // user actually sees — keeps wording consistent with the
        // initiative sidebar entry and panel header.
        label: advancedTool.name,
        path: urlGuildId
          ? guildPath(urlGuildId, "/settings/advanced-tool")
          : "/settings/advanced-tool",
      });
    }
    // Danger zone lives last — destructive guild deletion is deliberately
    // tucked behind its own tab rather than the first screen.
    tabs.push({
      value: "danger-zone",
      label: t("guildLayout.tabs.dangerZone"),
      path: urlGuildId ? guildPath(urlGuildId, "/settings/danger-zone") : "/settings/danger-zone",
    });
    return tabs;
  }, [urlGuildId, t, advancedTool]);

  const canViewSettings = isGuildAdmin;
  // A suspended guild refuses every /g content endpoint, so tabs backed by
  // them (AI, users, initiatives, trash, automations, auth) would only render
  // errors. Keep the surfaces that stay functional: the general tab (identity,
  // usage, plan) and the danger zone (deletion / data ownership).
  const isSuspended = activeGuild?.status === "suspended";
  const workingTabs = isSuspended
    ? guildSettingsTabs.filter((tab) => tab.value === "guild" || tab.value === "danger-zone")
    : guildSettingsTabs;
  const availableTabs = isGuildAdmin ? workingTabs : [];

  if (!canViewSettings) {
    return (
      <div className="space-y-4">
        <h1 className="font-semibold text-3xl tracking-tight">{t("guildLayout.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("guildLayout.permissionDenied")}</p>
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
    { value: "auth", subPath: "/settings/auth" },
    { value: "initiatives", subPath: "/settings/initiatives" },
    { value: "trash", subPath: "/settings/trash" },
    { value: "data", subPath: "/settings/data" },
    { value: "advanced-tool", subPath: "/settings/advanced-tool" },
    { value: "danger-zone", subPath: "/settings/danger-zone" },
  ];

  const activeTab =
    [...tabSubPaths]
      .sort((a, b) => b.subPath.length - a.subPath.length)
      .find((tab) => normalizedPath === tab.subPath || normalizedPath.startsWith(`${tab.subPath}/`))
      ?.value ??
    availableTabs[0]?.value ??
    "guild";

  // A read-only or suspended guild shows the admin a prominent notice pointing
  // them to the platform operator (the status reaches admins only — see the
  // backend GuildRead serialization). Static keys per status so the strict i18n
  // typing stays happy (a `${status}` template would include `active`).
  const statusNotice =
    activeGuild?.status === "suspended"
      ? {
          label: t("guildLayout.restricted.suspended.label"),
          message: t("guildLayout.restricted.suspended.message"),
        }
      : activeGuild?.status === "read_only"
        ? {
            label: t("guildLayout.restricted.read_only.label"),
            message: t("guildLayout.restricted.read_only.message"),
          }
        : null;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-semibold text-3xl tracking-tight">{t("guildLayout.title")}</h1>
          {statusNotice && <Badge variant="destructive">{statusNotice.label}</Badge>}
        </div>
        <p className="text-muted-foreground">{t("guildLayout.subtitle")}</p>
        {statusNotice && (
          <p className="font-bold text-destructive text-sm">{statusNotice.message}</p>
        )}
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
