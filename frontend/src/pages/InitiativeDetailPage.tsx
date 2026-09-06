import { Link, Navigate, useParams } from "@tanstack/react-router";
import { ChevronDown, Loader2, SearchX, Settings } from "lucide-react";
import { type ComponentType, Suspense, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Markdown } from "@/components/Markdown";
import { StatusMessage } from "@/components/StatusMessage";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import {
  canCreateTool,
  isToolVisible,
  useMyInitiativePermissions,
} from "@/hooks/useInitiativeRoles";
import { useInitiative } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { initiativeRoute, TOOLS, toolCamelPlural, toolListRoute } from "@/lib/tools";

import { DocumentsView } from "./DocumentsPage";
import { CounterGroupsView } from "./initiativeTools/counters/CounterGroupsPage";
import { DashboardsView } from "./initiativeTools/dashboards/DashboardsPage";
import { CalendarsView } from "./initiativeTools/events/CalendarsPage";
import { PostsView } from "./initiativeTools/posts/PostsPage";
import { QueuesView } from "./initiativeTools/queues/QueuesPage";
import { ProjectsView } from "./ProjectsPage";

type ToolViewProps = { fixedInitiativeId: number; canCreate?: boolean };

// Each tool's list view. A new tool adds one line here (the drift test
// asserts every tool has an entry); the tab ORDER is not restated — it is the
// registry's canonical order, so these tabs read in the same sequence as the
// guild home's tool rail.
const TOOL_VIEWS: Record<Tool, ComponentType<ToolViewProps>> = {
  [Tool.project]: ProjectsView,
  [Tool.document]: DocumentsView,
  [Tool.queue]: QueuesView,
  [Tool.counter_group]: CounterGroupsView,
  [Tool.calendar]: CalendarsView,
  [Tool.dashboard]: DashboardsView,
  [Tool.post]: PostsView,
};

const TOOL_TABS: Array<[Tool, ComponentType<ToolViewProps>]> = TOOLS.map((tool) => [
  tool,
  TOOL_VIEWS[tool],
]);

export const TOOL_TAB_VIEWS: ReadonlyMap<Tool, ComponentType<ToolViewProps>> = new Map(TOOL_TABS);

export interface InitiativeDetailPageProps {
  /** The tool tab the URL names. Omitted on the bare initiative route, where
   *  the page falls back to the first tab this member can see. */
  tool?: Tool;
}

export const InitiativeDetailPage = ({ tool }: InitiativeDetailPageProps = {}) => {
  const { initiativeId: initiativeIdParam } = useParams({
    strict: false,
  }) as {
    initiativeId: string;
  };
  const gp = useGuildPath();
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

  // Addressed by id, not picked out of the caller's own list: a guild admin
  // reaches every initiative in their guild whether or not they have joined it,
  // and the endpoint answers 404 to anyone the row is not visible to.
  const initiativeQuery = useInitiative(hasValidInitiativeId ? initiativeId : null);
  const initiative = initiativeQuery.data ?? null;
  const isGuildAdmin = activeGuild?.role === "admin";
  const membership = initiative?.members.find((member) => member.user.id === user?.id) ?? null;
  const isInitiativeManager = Boolean(membership?.is_manager);
  const canManageInitiative = Boolean(isGuildAdmin || isInitiativeManager);

  // A tool's tab renders when its permission allows viewing it (the backend
  // already folds in the initiative's master switches). The advanced tool is
  // additionally gated by the deployment-level runtime config.
  const availableTabs = useMemo<Tool[]>(
    () =>
      TOOL_TABS.map(([tabTool]) => tabTool).filter((tabTool) =>
        isToolVisible(permissions, tabTool)
      ),
    [permissions]
  );

  // The path names the tab, so it is shareable and survives a reload. A tool
  // this member can't view falls back to the first one they can, rather than
  // dead-ending a bookmark the moment a permission changes — the same rule the
  // guild home applies to its `?tool=` param.
  const activeTab =
    tool && availableTabs.includes(tool) ? tool : (availableTabs[0] ?? Tool.project);

  const memberCount = initiative?.members.length ?? 0;

  const roleBadgeLabel =
    permissions?.role_display_name ??
    membership?.role_display_name ??
    membership?.role_name ??
    (isGuildAdmin ? guildAdminLabel : null);

  if (!hasValidInitiativeId) {
    return <Navigate to={gp("/")} replace />;
  }

  if (initiativeQuery.isLoading || permissionsLoading) {
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
        backTo={gp("/")}
        backLabel={t("detail.backToInitiatives")}
      />
    );
  }

  // If user has no access to any features, show a message
  if (availableTabs.length === 0) {
    return (
      <div className="space-y-4">
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

  // Description + counts, rendered inline on wide screens and inside the
  // mobile disclosure — one definition, so the two can't drift.
  const headerDetails = (
    <>
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
    </>
  );

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* The header is context, not content. On a phone it stays a title row
          plus the settings gear; the badges, blurb, and counts sit one tap away
          in the disclosure rather than pushing the tool's list off screen.
          The row never wraps — a long name wraps its own text instead (it can
          shrink past its content, hence min-w-0), so the gear stays put. */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-2 sm:space-y-4">
          <div className="flex min-w-0 items-center gap-3">
            <InitiativeColorDot color={initiative.color} className="h-4 w-4 shrink-0" />
            <h1 className="min-w-0 break-words font-semibold text-xl tracking-tight sm:text-3xl">
              {initiative.name}
            </h1>
            <div className="hidden shrink-0 flex-wrap items-center gap-2 sm:flex">
              {initiative.is_default ? (
                <Badge variant="outline">{t("detail.default")}</Badge>
              ) : null}
              {roleBadgeLabel ? <Badge variant="secondary">{roleBadgeLabel}</Badge> : null}
            </div>
          </div>
          <div className="hidden space-y-4 sm:block">{headerDetails}</div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {canManageInitiative ? (
            <Button
              variant="outline"
              // Icon-only on a phone: the gear is unambiguous next to a title,
              // and the label is the widest thing in the header row.
              className="max-sm:h-9 max-sm:w-9 max-sm:p-0"
              asChild
            >
              <Link
                to={gp(`${initiativeRoute(initiative.id)}/settings`)}
                aria-label={t("detail.initiativeSettings")}
              >
                <Settings className="h-4 w-4" />
                <span className="hidden sm:inline">{t("detail.initiativeSettings")}</span>
              </Link>
            </Button>
          ) : null}
        </div>
      </div>

      <Collapsible className="group sm:hidden">
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 px-0 text-muted-foreground">
            {t("common:toolbar.details")}
            <ChevronDown className="h-4 w-4 transition-transform group-data-[state=open]:rotate-180" />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="space-y-3 pt-2">
          <div className="flex flex-wrap items-center gap-2">
            {initiative.is_default ? <Badge variant="outline">{t("detail.default")}</Badge> : null}
            {roleBadgeLabel ? <Badge variant="secondary">{roleBadgeLabel}</Badge> : null}
          </div>
          {headerDetails}
        </CollapsibleContent>
      </Collapsible>

      <Tabs value={activeTab}>
        <TabsBar>
          {TOOL_TABS.filter(([tabTool]) => availableTabs.includes(tabTool)).map(([tabTool]) => (
            <TabsTrigger key={tabTool} value={tabTool} asChild>
              {/* A real link, so a tab is shareable and answers the back
                    button. `search={{}}` clears the page cursor: all six tabs
                    now share one search schema, so a ?page from the queue tab
                    would otherwise follow the reader into documents. */}
              <Link to={gp(toolListRoute(tabTool, initiative.id))} search={{}}>
                {t(`detail.${toolCamelPlural(tabTool)}` as never)}
              </Link>
            </TabsTrigger>
          ))}
        </TabsBar>
        {TOOL_TABS.filter(([tabTool]) => availableTabs.includes(tabTool)).map(([tabTool, View]) => (
          <TabsContent key={tabTool} value={tabTool} className="mt-6">
            <Suspense fallback={tabFallback}>
              <View
                key={`${tabTool}-${initiative.id}`}
                fixedInitiativeId={initiative.id}
                canCreate={canCreateTool(permissions, tabTool)}
              />
            </Suspense>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
};
