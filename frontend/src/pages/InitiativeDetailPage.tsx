import { Link, Navigate, useParams } from "@tanstack/react-router";
import { Loader2, SearchX, Settings } from "lucide-react";
import { type ComponentType, Suspense, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Markdown } from "@/components/Markdown";
import { StatusMessage } from "@/components/StatusMessage";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import {
  canCreateTool,
  isToolVisible,
  useMyInitiativePermissions,
} from "@/hooks/useInitiativeRoles";
import { useInitiatives } from "@/hooks/useInitiatives";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { toolAvailable, toolCamelPlural } from "@/lib/tools";

import { DocumentsView } from "./DocumentsPage";
import { AdvancedToolsView } from "./initiativeTools/advancedTools/AdvancedToolsView";
import { CounterGroupsView } from "./initiativeTools/counters/CounterGroupsPage";
import { EventsView } from "./initiativeTools/events/EventsPage";
import { QueuesView } from "./initiativeTools/queues/QueuesPage";
import { ProjectsView } from "./ProjectsPage";

type ToolViewProps = { fixedInitiativeId: number; canCreate?: boolean };

// Tab display order + each tool's list view. A new tool adds one line here
// (the drift test asserts every tool has an entry).
const TOOL_TABS: Array<[Tool, ComponentType<ToolViewProps>]> = [
  [Tool.document, DocumentsView],
  [Tool.project, ProjectsView],
  [Tool.calendar_event, EventsView],
  [Tool.queue, QueuesView],
  [Tool.counter_group, CounterGroupsView],
  [Tool.advanced_tool, AdvancedToolsView],
];

export const TOOL_TAB_VIEWS: ReadonlyMap<Tool, ComponentType<ToolViewProps>> = new Map(TOOL_TABS);

export const InitiativeDetailPage = () => {
  const { initiativeId: initiativeIdParam, guildId: guildIdParam } = useParams({
    strict: false,
  }) as {
    initiativeId: string;
    guildId: string;
  };
  const parsedInitiativeId = Number(initiativeIdParam);
  const hasValidInitiativeId = Number.isFinite(parsedInitiativeId);
  const initiativeId = hasValidInitiativeId ? parsedInitiativeId : 0;
  const { t } = useTranslation(["initiatives", "common"]);
  const { user } = useAuth();
  const { activeGuild } = useGuilds();
  const guildAdminLabel = t("settings.guildAdminRole");

  // Fetch user's permissions for this initiative
  const { data: permissions, isLoading: permissionsLoading } = useMyInitiativePermissions(
    hasValidInitiativeId ? initiativeId : null
  );

  const initiativesQuery = useInitiatives({ enabled: hasValidInitiativeId });

  const initiative =
    hasValidInitiativeId && initiativesQuery.data
      ? (initiativesQuery.data.find((item) => item.id === initiativeId) ?? null)
      : null;
  const isGuildAdmin = activeGuild?.role === "admin";
  const membership = initiative?.members.find((member) => member.user.id === user?.id) ?? null;
  const isInitiativeManager = membership?.is_manager || membership?.role === "project_manager";
  const canManageInitiative = Boolean(isGuildAdmin || isInitiativeManager);

  const { advancedTool } = useAppConfig();

  // A tool's tab renders when its permission allows viewing it (the backend
  // already folds in the initiative's master switches). The advanced tool is
  // additionally gated by the deployment-level runtime config.
  const availableTabs = useMemo<Tool[]>(
    () =>
      TOOL_TABS.map(([tool]) => tool).filter(
        (tool) => isToolVisible(permissions, tool) && toolAvailable(tool, advancedTool)
      ),
    [permissions, advancedTool]
  );

  const [activeTab, setActiveTab] = useState<Tool>(availableTabs[0] ?? Tool.document);

  // Update active tab if current tab becomes unavailable
  useEffect(() => {
    if (availableTabs.length > 0 && !availableTabs.includes(activeTab)) {
      setActiveTab(availableTabs[0]);
    }
  }, [availableTabs, activeTab]);

  const memberCount = initiative?.members.length ?? 0;

  const roleBadgeLabel = permissions?.role_display_name
    ? permissions.role_display_name
    : membership
      ? (membership.role_display_name ?? membership.role)
      : isGuildAdmin
        ? guildAdminLabel
        : null;

  if (!hasValidInitiativeId) {
    return <Navigate to="/initiatives" replace />;
  }

  if (initiativesQuery.isLoading || permissionsLoading || !initiativesQuery.data) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("detail.loadingInitiative")}
      </div>
    );
  }

  if (!initiative) {
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("detail.notFound")}
        description={t("detail.notFoundDescription")}
        backTo="/initiatives"
        backLabel={t("detail.backToInitiatives")}
      />
    );
  }

  // If user has no access to any features, show a message
  if (availableTabs.length === 0) {
    return (
      <div className="space-y-4">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to="/initiatives">{t("detail.backToInitiatives")}</Link>
        </Button>
        <div className="rounded-lg border p-6">
          <div className="flex flex-wrap items-center gap-3">
            <InitiativeColorDot color={initiative.color} className="h-4 w-4" />
            <h1 className="font-semibold text-3xl tracking-tight">{initiative.name}</h1>
          </div>
          <p className="mt-4 text-muted-foreground">{t("detail.noAccess")}</p>
        </div>
      </div>
    );
  }

  // Local Suspense fallback for tab content — keeps the spinner below the tabs
  // while a lazily-loaded i18n namespace (queues/events/counters) resolves,
  // instead of letting the suspension bubble up to a full-page fallback.
  const tabFallback = (
    <div className="mt-6 flex items-center gap-2 text-muted-foreground text-sm">
      <Loader2 className="h-4 w-4 animate-spin" />
      {t("common:loading")}
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-4">
          <Button variant="link" size="sm" asChild className="px-0">
            <Link to="/initiatives">{t("detail.backToInitiatives")}</Link>
          </Button>
          <div className="flex flex-wrap items-center gap-3">
            <InitiativeColorDot color={initiative.color} className="h-4 w-4" />
            <h1 className="font-semibold text-3xl tracking-tight">{initiative.name}</h1>
            {initiative.is_default ? <Badge variant="outline">{t("detail.default")}</Badge> : null}
            {roleBadgeLabel ? <Badge variant="secondary">{roleBadgeLabel}</Badge> : null}
          </div>
          {initiative.description ? (
            <Markdown content={initiative.description} className="text-muted-foreground" />
          ) : (
            <p className="text-muted-foreground text-sm">{t("noDescription")}</p>
          )}
          <div className="flex flex-wrap items-center gap-4 text-muted-foreground text-sm">
            <span>{t("detail.member", { count: memberCount })}</span>
            <span>
              {t("detail.updated", { date: new Date(initiative.updated_at).toLocaleDateString() })}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {canManageInitiative ? (
            <Button variant="outline" asChild>
              <Link
                to="/g/$guildId/initiatives/$initiativeId/settings"
                params={{ guildId: guildIdParam, initiativeId: String(initiative.id) }}
              >
                <Settings className="mr-2 h-4 w-4" />
                {t("detail.initiativeSettings")}
              </Link>
            </Button>
          ) : null}
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as Tool)}>
        <div className="-mx-1 overflow-x-auto px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <TabsList className="inline-flex w-max">
            {TOOL_TABS.filter(([tool]) => availableTabs.includes(tool)).map(([tool]) => (
              <TabsTrigger key={tool} value={tool}>
                {t(`detail.${toolCamelPlural(tool)}` as never)}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        {TOOL_TABS.filter(([tool]) => availableTabs.includes(tool)).map(([tool, View]) => (
          <TabsContent key={tool} value={tool} className="mt-6">
            <Suspense fallback={tabFallback}>
              <View
                key={`${tool}-${initiative.id}`}
                fixedInitiativeId={initiative.id}
                canCreate={canCreateTool(permissions, tool)}
              />
            </Suspense>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
};
