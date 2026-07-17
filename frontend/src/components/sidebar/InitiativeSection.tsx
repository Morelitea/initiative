import { Link } from "@tanstack/react-router";
import { CircleChevronRight, MoreVertical, Settings } from "lucide-react";
import { memo, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRead, ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolCreateButton } from "@/components/tools/ToolCreateButton";
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
  toolAvailable,
  toolDisplayName,
  toolNavLabelKey,
  toolRowTarget,
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

    /** Whether a tool's row renders at all — the member can view it AND (for
     * config-gated tools) the deployment has the integration configured. */
    const showTool = (tool: Tool): boolean =>
      access[tool].view && toolAvailable(tool, advancedTool);

    /** Whether to surface a create affordance for a tool (same config gate). */
    const canCreateTool = (tool: Tool): boolean =>
      access[tool].create && toolAvailable(tool, advancedTool);

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
                    className="hidden h-6 w-0 shrink-0 overflow-hidden p-0 opacity-0 transition-all group-hover/initiative:w-6 group-hover/initiative:opacity-100 motion-reduce:transition-none lg:flex"
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

              {/* Mobile: Show three-dot menu. modal={false}: a modal dropdown
                  nested in the non-modal mobile sidebar drawer dismisses the
                  drawer on open (matches the user-footer dropdown). */}
              <DropdownMenu modal={false}>
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
                  {SIDEBAR_TOOLS.filter(canCreateTool).map((tool) => (
                    <ToolCreateButton
                      key={tool}
                      tool={tool}
                      initiativeId={initiative.id}
                      variant="menu-item"
                    />
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
              {/* One row per tool, in SIDEBAR_TOOLS order (advanced tool
                  pinned to the top so it's the first thing a user sees when
                  the integration is on; projects last so the project list
                  expands directly beneath their row). */}
              {SIDEBAR_TOOLS.filter(showTool).map((tool) => {
                const def = TOOL_REGISTRY[tool];
                const Icon = def.icon;
                const row = toolRowTarget(tool, initiative.id);
                return (
                  <SidebarMenuItem key={tool}>
                    <div className="group/tool flex w-full min-w-0 items-center gap-1">
                      <SidebarMenuButton asChild size="sm" className="min-w-0 flex-1">
                        <Link
                          to={gp(row.to)}
                          search={row.search}
                          className="flex min-w-0 items-center gap-2"
                        >
                          <Icon className="h-4 w-4" />
                          <span className="min-w-0 flex-1 truncate">
                            {toolDisplayName(tool, t(toolNavLabelKey(tool)), advancedTool)}
                          </span>
                          {def.sidebarCount && (
                            <span className="text-muted-foreground text-xs">
                              {counts[tool] ?? 0}
                            </span>
                          )}
                        </Link>
                      </SidebarMenuButton>
                      {canCreateTool(tool) && (
                        <ToolCreateButton tool={tool} initiativeId={initiative.id} variant="icon" />
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
                                className="hidden h-6 w-0 shrink-0 overflow-hidden p-0 opacity-0 transition-all group-hover/project:w-6 group-hover/project:opacity-100 motion-reduce:transition-none lg:flex"
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

                          {/* Mobile: Show three-dot menu. modal={false}: a modal
                              dropdown nested in the non-modal mobile sidebar
                              drawer dismisses the drawer on open (matches the
                              user-footer dropdown). */}
                          <DropdownMenu modal={false}>
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
