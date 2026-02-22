import { memo, useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  Settings,
  Plus,
  ScrollText,
  CircleChevronRight,
  ListTodo,
  MoreVertical,
} from "lucide-react";

import { getItem, setItem } from "@/lib/storage";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
} from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { guildPath } from "@/lib/guildUrl";
import type {
  InitiativeRead,
  ProjectRead,
} from "@/api/generated/initiativeAPI.schemas";

export interface InitiativeSectionProps {
  initiative: InitiativeRead;
  projects: ProjectRead[];
  documentCount: number;
  canManageInitiative: boolean;
  activeProjectId: number | null;
  userId: number | undefined;
  canViewDocs: boolean;
  canViewProjects: boolean;
  canCreateDocs: boolean;
  canCreateProjects: boolean;
  activeGuildId: number | null;
  /** Changing this value re-syncs the open/closed state from storage. */
  collapseKey?: number;
}

export const InitiativeSection = memo(
  ({
    initiative,
    projects,
    documentCount,
    canManageInitiative,
    activeProjectId,
    userId,
    canViewDocs,
    canViewProjects,
    canCreateDocs,
    canCreateProjects,
    activeGuildId,
    collapseKey,
  }: InitiativeSectionProps) => {
    const { t } = useTranslation("nav");
    // Helper to create guild-scoped paths
    const gp = (path: string) => (activeGuildId ? guildPath(activeGuildId, path) : path);
    // Pure DAC: check if user has write access to a specific project
    const canManageProject = (project: ProjectRead): boolean => {
      if (!userId) return false;
      const level = project.my_permission_level;
      return level === "owner" || level === "write";
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
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [collapseKey]);

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
              className="hover:bg-accent min-w-0 flex-1 justify-start px-0 py-1.5 text-sm font-medium"
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
                  {canCreateDocs && (
                    <DropdownMenuItem asChild>
                      <Link
                        to={gp("/documents")}
                        search={{ create: "true", initiativeId: String(initiative.id) }}
                      >
                        <Plus className="mr-2 h-4 w-4" />
                        {t("createDocument")}
                      </Link>
                    </DropdownMenuItem>
                  )}
                  {canCreateProjects && (
                    <DropdownMenuItem asChild>
                      <Link
                        to={gp("/projects")}
                        search={{ create: "true", initiativeId: String(initiative.id) }}
                      >
                        <Plus className="mr-2 h-4 w-4" />
                        {t("createProject")}
                      </Link>
                    </DropdownMenuItem>
                  )}
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
              {/* Documents Link */}
              {canViewDocs && (
              <SidebarMenuItem>
                <div className="group/documents flex w-full min-w-0 items-center gap-1">
                  <SidebarMenuButton asChild size="sm" className="min-w-0 flex-1">
                    <Link
                      to={gp("/documents")}
                      search={{ initiativeId: String(initiative.id) }}
                      className="flex items-center gap-2"
                    >
                      <ScrollText className="h-4 w-4" />
                      <span>{t("documents")}</span>
                      <span className="text-muted-foreground text-xs">{documentCount}</span>
                    </Link>
                  </SidebarMenuButton>
                  {canCreateDocs && (
                    <Tooltip delayDuration={300}>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="hidden h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover/documents:opacity-100 lg:flex"
                          asChild
                        >
                          <Link
                            to={gp("/documents")}
                            search={{ create: "true", initiativeId: String(initiative.id) }}
                          >
                            <Plus className="h-3 w-3" />
                          </Link>
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent side="top">
                        <p>{t("createDocument")}</p>
                      </TooltipContent>
                    </Tooltip>
                  )}
                </div>
              </SidebarMenuItem>
            )}

            {/* Projects Link */}
            {canViewProjects && (
              <SidebarMenuItem>
                <div className="group/projects flex w-full min-w-0 items-center gap-1">
                  <SidebarMenuButton asChild size="sm" className="min-w-0 flex-1">
                    <Link
                      to={gp("/projects")}
                      search={{ initiativeId: String(initiative.id) }}
                      className="flex items-center gap-2"
                    >
                      <ListTodo className="h-4 w-4" />
                      <span>{t("projects")}</span>
                      <span className="text-muted-foreground text-xs">{projects.length}</span>
                    </Link>
                  </SidebarMenuButton>
                  {canCreateProjects && (
                    <Tooltip delayDuration={300}>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="hidden h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover/projects:opacity-100 lg:flex"
                          asChild
                        >
                          <Link
                            to={gp("/projects")}
                            search={{ create: "true", initiativeId: String(initiative.id) }}
                          >
                            <Plus className="h-3 w-3" />
                          </Link>
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent side="top">
                        <p>{t("createProject")}</p>
                      </TooltipContent>
                    </Tooltip>
                  )}
                </div>
              </SidebarMenuItem>
            )}

            {/* Projects List */}
            {canViewProjects &&
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
