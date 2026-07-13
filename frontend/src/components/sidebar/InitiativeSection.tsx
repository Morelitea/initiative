import { Link } from "@tanstack/react-router";
import { CircleChevronRight, MoreVertical, Plus, Settings } from "lucide-react";
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
import type { InitiativeToolAccess } from "@/hooks/useInitiativeAccess";
import { guildPath } from "@/lib/guildUrl";
import { getItem, setItem } from "@/lib/storage";
import {
  SIDEBAR_TOOLS,
  TOOL_REGISTRY,
  toolCreateLabelKey,
  toolListRoute,
  toolNavLabelKey,
} from "@/lib/tools";
import { cn } from "@/lib/utils";

export interface InitiativeSectionProps {
  initiative: InitiativeRead;
  projects: ProjectRead[];
  canManageInitiative: boolean;
  activeProjectId: number | null;
  userId: number | undefined;
  /** Per-tool view/create access, from useInitiativeAccess().permissionsFor. */
  access: InitiativeToolAccess;
  /** Per-tool sidebar counts — only read for tools with sidebarCount. */
  counts: Partial<Record<Tool, number>>;
  activeGuildId: number | null;
  /** Changing this value re-syncs the open/closed state from storage. */
  collapseKey?: number;
}

export const InitiativeSection = memo(
  ({
    initiative,
    projects,
    canManageInitiative,
    activeProjectId,
    userId,
    access,
    counts,
    activeGuildId,
    collapseKey,
  }: InitiativeSectionProps) => {
    const { t } = useTranslation("nav");
    const { advancedTool } = useAppConfig();
    // Helper to create guild-scoped paths
    const gp = (path: string) => (activeGuildId ? guildPath(activeGuildId, path) : path);
    // Pure DAC: check if user has write access to a specific project
    const canManageProject = (project: ProjectRead): boolean => {
      if (!userId) return false;
      const level = project.my_permission_level;
      return level === "owner" || level === "write";
    };

    /** Whether a tool's row renders at all. `access[tool].view` already folds
     * in the initiative's master switch and the member's role permission; the
     * advanced tool is additionally gated by the deployment-level runtime
     * config (no integration configured → no row anywhere). */
    const showTool = (tool: Tool): boolean => {
      if (!access[tool].view) return false;
      if (tool === Tool.advanced_tool) return Boolean(advancedTool);
      return true;
    };

    /** Row target: every tool lists at its own route except the advanced
     * tool, which is one embedded page per initiative. */
    const toolLink = (tool: Tool) =>
      tool === Tool.advanced_tool
        ? { to: gp(`/initiatives/${initiative.id}/advanced-tool`), search: undefined }
        : { to: gp(toolListRoute(tool)), search: { initiativeId: String(initiative.id) } };

    /** The advanced tool renders under the deployment's own name for it. */
    const toolLabel = (tool: Tool): string =>
      tool === Tool.advanced_tool && advancedTool?.name
        ? advancedTool.name
        : t(toolNavLabelKey(tool));

    /** Whether to surface a create affordance for a tool. Mirrors showTool's
     * deployment-config gate for the advanced tool (no integration → no create). */
    const canCreateTool = (tool: Tool): boolean =>
      access[tool].create && (tool !== Tool.advanced_tool || Boolean(advancedTool));

    /** Create target for a tool. Regular tools open a create dialog at their
     * list route; the advanced tool hands off to its embedded external page
     * with a "new" intent (authoring happens fully in that service, not here). */
    const createLink = (tool: Tool) =>
      tool === Tool.advanced_tool
        ? { to: gp(`/initiatives/${initiative.id}/advanced-tool`), search: { create: "true" } }
        : {
            to: gp(toolListRoute(tool)),
            search: { create: "true", initiativeId: String(initiative.id) },
          };

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
                  {SIDEBAR_TOOLS.filter(canCreateTool).map((tool) => {
                    const link = createLink(tool);
                    return (
                      <DropdownMenuItem key={tool} asChild>
                        <Link to={link.to} search={link.search}>
                          <Plus className="mr-2 h-4 w-4" />
                          {t(toolCreateLabelKey(tool))}
                        </Link>
                      </DropdownMenuItem>
                    );
                  })}
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
              {/* One row per tool, in SIDEBAR_TOOLS order (advanced tool
                  pinned to the top so it's the first thing a user sees when
                  the integration is on; projects last so the project list
                  expands directly beneath their row). */}
              {SIDEBAR_TOOLS.filter(showTool).map((tool) => {
                const def = TOOL_REGISTRY[tool];
                const Icon = def.icon;
                const link = toolLink(tool);
                return (
                  <SidebarMenuItem key={tool}>
                    <div className="group/tool flex w-full min-w-0 items-center gap-1">
                      <SidebarMenuButton asChild size="sm" className="min-w-0 flex-1">
                        <Link
                          to={link.to}
                          search={link.search}
                          className="flex min-w-0 items-center gap-2"
                        >
                          <Icon className="h-4 w-4" />
                          <span className="min-w-0 flex-1 truncate">{toolLabel(tool)}</span>
                          {def.sidebarCount && (
                            <span className="text-muted-foreground text-xs">
                              {counts[tool] ?? 0}
                            </span>
                          )}
                        </Link>
                      </SidebarMenuButton>
                      {canCreateTool(tool) && (
                        <Tooltip delayDuration={300}>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="hidden h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover/tool:opacity-100 lg:flex"
                              asChild
                            >
                              {/* Regular tools open a create dialog at their list
                                  route; the advanced tool hands off to its embedded
                                  external page with a "new" intent. */}
                              <Link to={createLink(tool).to} search={createLink(tool).search}>
                                <Plus className="h-3 w-3" />
                              </Link>
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent side="top">
                            <p>{t(toolCreateLabelKey(tool))}</p>
                          </TooltipContent>
                        </Tooltip>
                      )}
                    </div>
                  </SidebarMenuItem>
                );
              })}

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
