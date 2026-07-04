import { Link } from "@tanstack/react-router";
import { CircleChevronRight, MoreVertical, Plus, Settings, Sparkles } from "lucide-react";
import { memo, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRead, ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAppConfig } from "@/hooks/useAppConfig";
import { guildPath } from "@/lib/guildUrl";
import { getItem, setItem } from "@/lib/storage";
import { TOOL_BY_ID, type ToolAccessMap, type ToolDef } from "@/lib/tools/registry";
import { cn } from "@/lib/utils";

// The order tools appear in an initiative's sidebar section. Each entry is
// rendered by the shared <ToolNavRow> below — no more copy-pasted blocks. The
// advanced tool is intentionally NOT here: it renders a bespoke pinned entry
// (its label is the deployment's runtime name, its route is per-initiative).
const SIDEBAR_TOOLS: ToolDef[] = [
  TOOL_BY_ID[Tool.calendar_event],
  TOOL_BY_ID[Tool.document],
  TOOL_BY_ID[Tool.queue],
  TOOL_BY_ID[Tool.counter_group],
  TOOL_BY_ID[Tool.project],
];

export interface InitiativeSectionProps {
  initiative: InitiativeRead;
  projects: ProjectRead[];
  /** Per-tool visibility/creation for the current user (from useInitiativeAccess). */
  access: ToolAccessMap;
  /** Item counts by tool id (documents, queues, counter groups, projects). */
  counts: Partial<Record<Tool, number>>;
  canManageInitiative: boolean;
  activeProjectId: number | null;
  userId: number | undefined;
  activeGuildId: number | null;
  /** Changing this value re-syncs the open/closed state from storage. */
  collapseKey?: number;
}

/** One tool link row — icon, label, optional count, and a hover-reveal "+" create. */
const ToolNavRow = ({
  tool,
  initiativeId,
  count,
  canCreate,
  gp,
}: {
  tool: ToolDef;
  initiativeId: number;
  count: number | undefined;
  canCreate: boolean;
  gp: (path: string) => string;
}) => {
  const { t } = useTranslation("nav");
  const nav = tool.nav;
  if (!nav) return null;
  const Icon = tool.icon;
  return (
    <SidebarMenuItem>
      <div className="group/toolrow flex w-full min-w-0 items-center gap-1">
        <SidebarMenuButton asChild size="sm" className="min-w-0 flex-1">
          <Link
            to={gp(nav.listRoute)}
            search={{ initiativeId: String(initiativeId) }}
            className="flex items-center gap-2"
          >
            <Icon className="h-4 w-4" />
            <span>{t(nav.labelKey as never)}</span>
            {nav.hasCount && <span className="text-muted-foreground text-xs">{count ?? 0}</span>}
          </Link>
        </SidebarMenuButton>
        {canCreate && (
          <Tooltip delayDuration={300}>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="hidden h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover/toolrow:opacity-100 lg:flex"
                asChild
              >
                <Link
                  to={gp(nav.listRoute)}
                  search={{ create: "true", initiativeId: String(initiativeId) }}
                >
                  <Plus className="h-3 w-3" />
                </Link>
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top">
              <p>{t(nav.createLabelKey as never)}</p>
            </TooltipContent>
          </Tooltip>
        )}
      </div>
    </SidebarMenuItem>
  );
};

export const InitiativeSection = memo(
  ({
    initiative,
    projects,
    access,
    counts,
    canManageInitiative,
    activeProjectId,
    userId,
    activeGuildId,
    collapseKey,
  }: InitiativeSectionProps) => {
    const { t } = useTranslation("nav");
    const { advancedTool } = useAppConfig();
    // The advanced tool entry is triply-gated:
    //   1. Runtime config must expose an advanced tool (deployment-level).
    //   2. The initiative manager must have enabled it (per-initiative).
    //   3. The user's role must include the advanced_tool view key
    //      — folded into access[advanced_tool].view.
    const showAdvancedTool = Boolean(
      advancedTool && initiative.advanced_tool_enabled && access[Tool.advanced_tool].view
    );
    // Helper to create guild-scoped paths
    const gp = (path: string) => (activeGuildId ? guildPath(activeGuildId, path) : path);
    // Pure DAC: check if user has write access to a specific project
    const canManageProject = (project: ProjectRead): boolean => {
      if (!userId) return false;
      const level = project.my_permission_level;
      return level === "owner" || level === "write";
    };
    // Tools the user may create, in sidebar order — drives the mobile "+" menu.
    const creatableTools = SIDEBAR_TOOLS.filter((tool) => access[tool.id].create);
    // Load initial state from storage, default to true if not found
    const [isOpen, setIsOpen] = useState(() => {
      try {
        const stored = getItem("initiative-collapsed-states");
        if (stored) {
          const states = JSON.parse(stored) as Record<number, boolean>;
          return states[initiative.id] ?? true;
        }
      } catch {
        // Ignore parsing errors
      }
      return true;
    });

    // Save state to storage whenever it changes
    useEffect(() => {
      try {
        const stored = getItem("initiative-collapsed-states");
        const states = stored ? (JSON.parse(stored) as Record<number, boolean>) : {};
        states[initiative.id] = isOpen;
        setItem("initiative-collapsed-states", JSON.stringify(states));
      } catch {
        // Ignore storage errors
      }
    }, [isOpen, initiative.id]);

    // Re-sync from storage when collapseKey changes (collapse/expand all)
    useEffect(() => {
      if (collapseKey === undefined) return;
      try {
        const stored = getItem("initiative-collapsed-states");
        if (stored) {
          const states = JSON.parse(stored) as Record<number, boolean>;
          setIsOpen(states[initiative.id] ?? true);
        }
      } catch {
        // Ignore parsing errors
      }
    }, [collapseKey, initiative.id]);

    return (
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <div className="group/initiative flex min-w-0 items-center gap-1">
          <div className="flex min-w-0 flex-1 items-center">
            <CollapsibleTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                aria-label={isOpen ? t("collapseInitiative") : t("expandInitiative")}
              >
                <CircleChevronRight
                  className={cn("h-4 w-4 transition-transform", isOpen && "rotate-90")}
                  style={{ color: initiative.color || undefined }}
                />
              </Button>
            </CollapsibleTrigger>
            <Button
              variant="ghost"
              className="min-w-0 flex-1 justify-start px-0 py-1.5 font-medium text-sm hover:bg-accent"
              asChild
            >
              <Link to={gp(`/initiatives/${initiative.id}`)} className="flex min-w-0 items-center">
                <span className="min-w-0 flex-1 truncate text-left">{initiative.name}</span>
              </Link>
            </Button>
          </div>
          {canManageInitiative && (
            <>
              {/* Desktop: Show hover-reveal settings button */}
              <Tooltip delayDuration={300}>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="hidden h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover/initiative:opacity-100 lg:flex"
                    asChild
                  >
                    <Link to={gp(`/initiatives/${initiative.id}/settings`)}>
                      <Settings className="h-3 w-3" />
                    </Link>
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top">
                  <p>{t("initiativeSettings")}</p>
                </TooltipContent>
              </Tooltip>

              {/* Mobile: Show three-dot menu */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0 lg:hidden"
                    aria-label={t("initiativeActions")}
                  >
                    <MoreVertical className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuItem asChild>
                    <Link to={gp(`/initiatives/${initiative.id}/settings`)}>
                      <Settings className="mr-2 h-4 w-4" />
                      {t("initiativeSettings")}
                    </Link>
                  </DropdownMenuItem>
                  {creatableTools.map((tool) => (
                    <DropdownMenuItem key={tool.id} asChild>
                      <Link
                        to={gp(tool.nav!.listRoute)}
                        search={{ create: "true", initiativeId: String(initiative.id) }}
                      >
                        <Plus className="mr-2 h-4 w-4" />
                        {t(tool.nav!.createLabelKey as never)}
                      </Link>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          )}
        </div>
        {isOpen && (
          <CollapsibleContent
            className="ml-3 space-y-0.5 border-l"
            style={{ borderColor: initiative.color || undefined }}
            forceMount
          >
            <SidebarMenu>
              {/* Advanced Tool — pinned to the top of the initiative so it's the
                  first thing a user sees when the integration is on. */}
              {showAdvancedTool && advancedTool && (
                <SidebarMenuItem>
                  <SidebarMenuButton asChild size="sm" className="min-w-0 flex-1">
                    <Link
                      to={gp(`/initiatives/${initiative.id}/advanced-tool`)}
                      className="flex items-center gap-2"
                    >
                      <Sparkles className="h-4 w-4" />
                      <span className="min-w-0 flex-1 truncate">{advancedTool.name}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              )}

              {/* Standard tool rows — one shared component per registry entry. */}
              {SIDEBAR_TOOLS.map((tool) =>
                access[tool.id].view ? (
                  <ToolNavRow
                    key={tool.id}
                    tool={tool}
                    initiativeId={initiative.id}
                    count={counts[tool.id]}
                    canCreate={access[tool.id].create}
                    gp={gp}
                  />
                ) : null
              )}

              {/* Projects List */}
              {access[Tool.project].view &&
                projects.map((project) => (
                  <SidebarMenuItem key={project.id}>
                    <div className="group/project flex w-full min-w-0 items-center gap-1">
                      <SidebarMenuButton
                        asChild
                        size="sm"
                        className="min-w-0 flex-1"
                        isActive={project.id === activeProjectId}
                      >
                        <Link
                          to={gp(`/projects/${project.id}`)}
                          className="flex min-w-0 items-center gap-2"
                        >
                          {project.icon ? (
                            <span className="shrink-0 text-base">{project.icon}</span>
                          ) : null}
                          <span className="min-w-0 flex-1 truncate">{project.name}</span>
                        </Link>
                      </SidebarMenuButton>
                      {canManageProject(project) && (
                        <>
                          {/* Desktop: Show hover-reveal settings button */}
                          <Tooltip delayDuration={300}>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="hidden h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover/project:opacity-100 lg:flex"
                                asChild
                              >
                                <Link to={gp(`/projects/${project.id}/settings`)}>
                                  <Settings className="h-3 w-3" />
                                </Link>
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent side="top">
                              <p>{t("projectSettings")}</p>
                            </TooltipContent>
                          </Tooltip>

                          {/* Mobile: Show three-dot menu */}
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 shrink-0 lg:hidden"
                                aria-label={t("projectActions")}
                              >
                                <MoreVertical className="h-4 w-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-48">
                              <DropdownMenuItem asChild>
                                <Link to={gp(`/projects/${project.id}/settings`)}>
                                  <Settings className="mr-2 h-4 w-4" />
                                  {t("projectSettings")}
                                </Link>
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </>
                      )}
                    </div>
                  </SidebarMenuItem>
                ))}
            </SidebarMenu>
          </CollapsibleContent>
        )}
      </Collapsible>
    );
  }
);
InitiativeSection.displayName = "InitiativeSection";
