import { useMemo, useState, useEffect } from "react";
import { Link, useLocation } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { useAutoCloseSidebar } from "@/hooks/useAutoCloseSidebar";
import {
  Settings,
  Plus,
  ScrollText,
  Star,
  CircleChevronRight,
  Users,
  ListTodo,
  MoreVertical,
  ChartColumn,
  SquareCheckBig,
  UserCog,
  Tag,
} from "lucide-react";
import { SiGithub } from "@icons-pack/react-simple-icons";

import { apiClient } from "@/api/client";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { VersionDialog } from "@/components/VersionDialog";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarSeparator,
} from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { GuildSidebar } from "@/components/guilds/GuildSidebar";
import { ModeToggle } from "@/components/ModeToggle";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { useDockerHubVersion, compareVersions } from "@/hooks/useDockerHubVersion";
import { useTags } from "@/hooks/useTags";
import { cn } from "@/lib/utils";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { useIsMobile } from "@/hooks/use-mobile";
import type { Initiative, Project, Tag as TagType } from "@/types/api";

export const AppSidebar = () => {
  const { user, logout } = useAuth();
  const { activeGuild, activeGuildId } = useGuilds();
  const isMobile = useIsMobile();
  const location = useLocation();

  // Auto-close sidebar on mobile after navigation
  useAutoCloseSidebar();

  // Guild admin check is based on guild membership role only (independent from platform role)
  const isGuildAdmin = activeGuild?.role === "admin";
  // Platform admins can access platform settings (separate from guild admin role)
  const isPlatformAdmin = user?.role === "admin";

  // Extract active project ID from URL
  const activeProjectId = useMemo(() => {
    const match = location.pathname.match(/^\/projects\/(\d+)/);
    return match ? parseInt(match[1], 10) : null;
  }, [location.pathname]);

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: ["initiatives", activeGuildId],
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
    enabled: Boolean(activeGuild),
    staleTime: 60_000,
  });

  const projectsQuery = useQuery<Project[]>({
    queryKey: ["projects", activeGuildId],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/");
      return response.data;
    },
    enabled: Boolean(activeGuild),
    staleTime: 60_000,
  });

  const favoritesQuery = useQuery<Project[]>({
    queryKey: ["projects", activeGuildId, "favorites"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/favorites");
      return response.data;
    },
    enabled: activeGuildId !== null,
    staleTime: 60_000,
  });

  const documentsQuery = useQuery<{ id: number; initiative_id: number }[]>({
    queryKey: ["documents", activeGuildId],
    queryFn: async () => {
      const response = await apiClient.get<{ id: number; initiative_id: number }[]>("/documents/");
      return response.data;
    },
    enabled: Boolean(activeGuild),
    staleTime: 60_000,
  });

  const projectsByInitiative = useMemo(() => {
    const map = new Map<number, Project[]>();
    const projects = Array.isArray(projectsQuery.data) ? projectsQuery.data : [];
    projects.forEach((project) => {
      if (!project.is_archived) {
        const existing = map.get(project.initiative_id) ?? [];
        map.set(project.initiative_id, [...existing, project]);
      }
    });
    return map;
  }, [projectsQuery.data]);

  const documentCountsByInitiative = useMemo(() => {
    const map = new Map<number, number>();
    const documents = Array.isArray(documentsQuery.data) ? documentsQuery.data : [];
    documents.forEach((doc) => {
      const count = map.get(doc.initiative_id) ?? 0;
      map.set(doc.initiative_id, count + 1);
    });
    return map;
  }, [documentsQuery.data]);

  const visibleInitiatives = useMemo(() => {
    if (!user) {
      return [];
    }
    const source = initiativesQuery.data ?? [];
    if (isGuildAdmin) {
      return source.slice().sort((a, b) => a.name.localeCompare(b.name));
    }
    const membershipFiltered = source.filter((initiative) =>
      initiative.members.some((member) => member.user.id === user.id)
    );
    return membershipFiltered.sort((a, b) => a.name.localeCompare(b.name));
  }, [initiativesQuery.data, user, isGuildAdmin]);

  // Check if user can manage a specific initiative
  const canManageInitiative = (initiative: Initiative): boolean => {
    if (isGuildAdmin) {
      return true;
    }
    if (!user) {
      return false;
    }
    return initiative.members.some(
      (member) => member.user.id === user.id && member.role === "project_manager"
    );
  };

  // Get user's permissions for an initiative
  const getUserPermissions = (initiative: Initiative) => {
    if (!user) {
      return {
        canViewDocs: true,
        canViewProjects: true,
        canCreateDocs: false,
        canCreateProjects: false,
      };
    }
    // Guild admins have all permissions
    if (isGuildAdmin) {
      return {
        canViewDocs: true,
        canViewProjects: true,
        canCreateDocs: true,
        canCreateProjects: true,
      };
    }
    const membership = initiative.members.find((m) => m.user.id === user.id);
    if (!membership) {
      return {
        canViewDocs: true,
        canViewProjects: true,
        canCreateDocs: false,
        canCreateProjects: false,
      };
    }
    return {
      canViewDocs: membership.can_view_docs ?? true,
      canViewProjects: membership.can_view_projects ?? true,
      canCreateDocs: membership.can_create_docs ?? false,
      canCreateProjects: membership.can_create_projects ?? false,
    };
  };

  const userDisplayName = user?.full_name ?? user?.email ?? "User";
  const userEmail = user?.email ?? "";
  const userInitials =
    userDisplayName
      .split(/\s+/)
      .map((part) => part.charAt(0).toUpperCase())
      .join("")
      .slice(0, 2) || "U";
  const avatarSrc = resolveUploadUrl(user?.avatar_url) || user?.avatar_base64 || null;

  // Fetch tags for the tag browser
  const tagsQuery = useTags();

  // Fetch latest DockerHub version
  const { data: latestVersion, isLoading: isLoadingVersion } = useDockerHubVersion();
  const currentVersion = __APP_VERSION__;
  const hasUpdate =
    latestVersion && currentVersion && compareVersions(latestVersion, currentVersion) > 0;

  return (
    <Sidebar
      className="sticky top-0 h-screen"
      variant="sidebar"
      collapsible={isMobile ? "offcanvas" : "none"}
    >
      <div className="flex h-full w-full max-w-full min-w-0 flex-col">
        <div className="flex min-h-0 max-w-full flex-1">
          <GuildSidebar />
          <div className="flex max-w-full min-w-0 flex-1 flex-col overflow-hidden border-r">
            <SidebarHeader className="border-b">
              <div className="flex min-w-0 items-center justify-between gap-2 p-4">
                <h2 className="min-w-0 flex-1 truncate text-lg font-semibold">
                  {activeGuild?.name ?? "Select a Guild"}
                </h2>
                {activeGuild && isGuildAdmin && (
                  <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" asChild>
                    <Link to="/settings/guild" aria-label="Guild settings">
                      <Settings className="h-4 w-4" />
                    </Link>
                  </Button>
                )}
              </div>
            </SidebarHeader>

            <Tabs defaultValue="initiatives" className="flex flex-1 flex-col overflow-hidden">
              {/* <div className="border-b px-2"> */}
              <TabsList className="h-9 w-full rounded-none">
                <TabsTrigger value="initiatives" className="flex-1 text-xs">
                  <Users className="mr-2 h-3.5 w-3.5" />
                  Initiatives
                </TabsTrigger>
                <TabsTrigger value="tags" className="flex-1 text-xs">
                  <Tag className="mr-2 h-3.5 w-3.5" />
                  Tags
                </TabsTrigger>
              </TabsList>
              {/* </div> */}

              <TabsContent value="initiatives" className="mt-0 flex-1 overflow-hidden">
                <SidebarContent className="h-full overflow-x-hidden overflow-y-auto">
                  {/* Favorites Section */}
                  {favoritesQuery?.data && favoritesQuery.data.length > 0 && (
                    <>
                      <SidebarGroup>
                        <SidebarGroupLabel className="flex items-center gap-2 py-2">
                          <Star className="h-4 w-4" />
                          Favorites
                        </SidebarGroupLabel>
                        <SidebarGroupContent>
                          <SidebarMenu>
                            {favoritesQuery.data.map((project) => (
                              <SidebarMenuItem key={project.id}>
                                <SidebarMenuButton
                                  asChild
                                  isActive={project.id === activeProjectId}
                                >
                                  <Link
                                    to="/projects/$projectId"
                                    params={{ projectId: String(project.id) }}
                                    className="flex min-w-0 items-center gap-2"
                                  >
                                    {project.icon ? (
                                      <span className="shrink-0 text-lg">{project.icon}</span>
                                    ) : null}
                                    <span className="min-w-0 flex-1 truncate">{project.name}</span>
                                  </Link>
                                </SidebarMenuButton>
                              </SidebarMenuItem>
                            ))}
                          </SidebarMenu>
                        </SidebarGroupContent>
                      </SidebarGroup>
                      <SidebarSeparator />
                    </>
                  )}

                  {/* Initiatives Section */}
                  <SidebarGroup>
                    <SidebarGroupLabel className="flex items-center gap-2 py-2">
                      <Users className="h-4 w-4" /> Initiatives
                    </SidebarGroupLabel>
                    <SidebarGroupContent>
                      {initiativesQuery.isLoading ? (
                        <div className="space-y-2 px-4">
                          <Skeleton className="h-8 w-full" />
                          <Skeleton className="h-8 w-full" />
                          <Skeleton className="h-8 w-full" />
                        </div>
                      ) : visibleInitiatives.length === 0 ? (
                        <div className="text-muted-foreground px-4 py-2 text-sm">
                          No initiatives available
                        </div>
                      ) : (
                        <div className="space-y-1">
                          {visibleInitiatives.map((initiative) => {
                            const permissions = getUserPermissions(initiative);
                            return (
                              <InitiativeSection
                                key={initiative.id}
                                initiative={initiative}
                                projects={projectsByInitiative.get(initiative.id) ?? []}
                                documentCount={documentCountsByInitiative.get(initiative.id) ?? 0}
                                canManageInitiative={canManageInitiative(initiative)}
                                activeProjectId={activeProjectId}
                                userId={user?.id}
                                canViewDocs={permissions.canViewDocs}
                                canViewProjects={permissions.canViewProjects}
                                canCreateDocs={permissions.canCreateDocs}
                                canCreateProjects={permissions.canCreateProjects}
                              />
                            );
                          })}
                        </div>
                      )}

                      {isGuildAdmin && (
                        <SidebarMenu>
                          <SidebarMenuItem>
                            <SidebarMenuButton asChild size="sm">
                              <Link to="/initiatives" search={{ create: "true" }}>
                                <Plus className="h-4 w-4" />
                                <span>Add initiative</span>
                              </Link>
                            </SidebarMenuButton>
                          </SidebarMenuItem>
                        </SidebarMenu>
                      )}
                    </SidebarGroupContent>
                  </SidebarGroup>
                </SidebarContent>
              </TabsContent>

              <TabsContent value="tags" className="mt-0 flex-1 overflow-hidden">
                <SidebarContent className="h-full overflow-x-hidden overflow-y-auto">
                  <SidebarGroup>
                    <SidebarGroupLabel className="flex items-center gap-2 py-2">
                      <Tag className="h-4 w-4" /> Tags
                    </SidebarGroupLabel>
                    <SidebarGroupContent>
                      <TagBrowser tags={tagsQuery.data ?? []} isLoading={tagsQuery.isLoading} />
                    </SidebarGroupContent>
                  </SidebarGroup>
                </SidebarContent>
              </TabsContent>
            </Tabs>
          </div>
        </div>

        <SidebarFooter className="border-t border-r">
          <div className="flex flex-col">
            <div className="flex items-center gap-2 p-2">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    className="h-auto min-w-0 flex-1 justify-start gap-2 px-2 py-2"
                  >
                    <Avatar className="h-8 w-8 shrink-0">
                      {avatarSrc ? <AvatarImage src={avatarSrc} alt={userDisplayName} /> : null}
                      <AvatarFallback className="text-xs">{userInitials}</AvatarFallback>
                    </Avatar>
                    <div className="flex min-w-0 flex-1 flex-col items-start overflow-hidden text-left">
                      <span className="w-full truncate text-sm font-medium">{userDisplayName}</span>
                      <span className="text-muted-foreground w-full truncate text-xs">
                        {userEmail}
                      </span>
                    </div>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <DropdownMenuLabel>My Account</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem asChild>
                    <Link to="/">
                      <SquareCheckBig className="h-4 w-4" /> My Tasks
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <Link to="/user-stats">
                      <ChartColumn className="h-4 w-4" /> My Stats
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <Link to="/profile">
                      <UserCog className="h-4 w-4" /> User Settings
                    </Link>
                  </DropdownMenuItem>
                  {isGuildAdmin && (
                    <DropdownMenuItem asChild>
                      <Link to="/settings/guild">
                        <Settings className="h-4 w-4" /> Guild Settings
                      </Link>
                    </DropdownMenuItem>
                  )}
                  {isPlatformAdmin && (
                    <DropdownMenuItem asChild>
                      <Link to="/settings/admin">
                        <Settings className="h-4 w-4" /> Platform Settings
                      </Link>
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onSelect={() => logout()}>Sign out</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              <div className="flex shrink-0 items-center gap-1">
                {user && <NotificationBell />}
                <ModeToggle />
              </div>
            </div>
            <div className="border-t">
              <div className="flex items-center justify-between px-3 py-2">
                <VersionDialog
                  currentVersion={currentVersion}
                  latestVersion={latestVersion ?? null}
                  hasUpdate={Boolean(hasUpdate)}
                  isLoadingVersion={isLoadingVersion}
                >
                  <button className="flex cursor-pointer items-center gap-1.5">
                    <span className="text-muted-foreground hover:text-foreground text-xs transition-colors">
                      v{currentVersion}
                    </span>
                    {hasUpdate && (
                      <Badge variant="default" className="h-4 px-1.5 text-[10px]">
                        NEW
                      </Badge>
                    )}
                  </button>
                </VersionDialog>

                <Tooltip delayDuration={300}>
                  <TooltipTrigger asChild>
                    <a
                      href="https://github.com/Morelitea/initiative"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-muted-foreground hover:text-foreground transition-colors"
                      aria-label="View on GitHub"
                    >
                      <SiGithub className="h-4 w-4" />
                    </a>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <p>View on GitHub</p>
                  </TooltipContent>
                </Tooltip>
              </div>
            </div>
          </div>
        </SidebarFooter>
      </div>
    </Sidebar>
  );
};

interface InitiativeSectionProps {
  initiative: Initiative;
  projects: Project[];
  documentCount: number;
  canManageInitiative: boolean;
  activeProjectId: number | null;
  userId: number | undefined;
  canViewDocs: boolean;
  canViewProjects: boolean;
  canCreateDocs: boolean;
  canCreateProjects: boolean;
}

const InitiativeSection = ({
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
}: InitiativeSectionProps) => {
  // Pure DAC: check if user has write access to a specific project
  const canManageProject = (project: Project): boolean => {
    if (!userId) return false;
    const permission = project.permissions?.find((p) => p.user_id === userId);
    return permission?.level === "owner" || permission?.level === "write";
  };
  // Load initial state from localStorage, default to true if not found
  const [isOpen, setIsOpen] = useState(() => {
    try {
      const stored = localStorage.getItem("initiative-collapsed-states");
      if (stored) {
        const states = JSON.parse(stored) as Record<number, boolean>;
        return states[initiative.id] ?? true;
      }
    } catch {
      // Ignore parsing errors
    }
    return true;
  });

  // Save state to localStorage whenever it changes
  useEffect(() => {
    try {
      const stored = localStorage.getItem("initiative-collapsed-states");
      const states = stored ? (JSON.parse(stored) as Record<number, boolean>) : {};
      states[initiative.id] = isOpen;
      localStorage.setItem("initiative-collapsed-states", JSON.stringify(states));
    } catch {
      // Ignore storage errors
    }
  }, [isOpen, initiative.id]);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <div className="group/initiative flex min-w-0 items-center gap-1">
        <div className="flex min-w-0 flex-1 items-center">
          <CollapsibleTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0"
              aria-label={isOpen ? "Collapse initiative" : "Expand initiative"}
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
            <Link
              to="/initiatives/$initiativeId"
              params={{ initiativeId: String(initiative.id) }}
              className="flex min-w-0 items-center"
            >
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
                  <Link
                    to="/initiatives/$initiativeId/settings"
                    params={{ initiativeId: String(initiative.id) }}
                  >
                    <Settings className="h-3 w-3" />
                  </Link>
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">
                <p>Initiative Settings</p>
              </TooltipContent>
            </Tooltip>

            {/* Mobile: Show three-dot menu */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0 lg:hidden"
                  aria-label="Initiative actions"
                >
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuItem asChild>
                  <Link
                    to="/initiatives/$initiativeId/settings"
                    params={{ initiativeId: String(initiative.id) }}
                  >
                    <Settings className="mr-2 h-4 w-4" />
                    Initiative Settings
                  </Link>
                </DropdownMenuItem>
                {canCreateDocs && (
                  <DropdownMenuItem asChild>
                    <Link
                      to="/documents"
                      search={{ create: "true", initiativeId: String(initiative.id) }}
                    >
                      <Plus className="mr-2 h-4 w-4" />
                      Create Document
                    </Link>
                  </DropdownMenuItem>
                )}
                {canCreateProjects && (
                  <DropdownMenuItem asChild>
                    <Link
                      to="/projects"
                      search={{ create: "true", initiativeId: String(initiative.id) }}
                    >
                      <Plus className="mr-2 h-4 w-4" />
                      Create Project
                    </Link>
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        )}
      </div>
      <CollapsibleContent
        className="ml-3 space-y-0.5 border-l"
        style={{ borderColor: initiative.color || undefined }}
      >
        <SidebarMenu>
          {/* Documents Link */}
          {canViewDocs && (
            <SidebarMenuItem>
              <div className="group/documents flex w-full min-w-0 items-center gap-1">
                <SidebarMenuButton asChild size="sm" className="min-w-0 flex-1">
                  <Link
                    to="/documents"
                    search={{ initiativeId: String(initiative.id) }}
                    className="flex items-center gap-2"
                  >
                    <ScrollText className="h-4 w-4" />
                    <span>Documents</span>
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
                          to="/documents"
                          search={{ create: "true", initiativeId: String(initiative.id) }}
                        >
                          <Plus className="h-3 w-3" />
                        </Link>
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      <p>Create Document</p>
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
                    to="/projects"
                    search={{ initiativeId: String(initiative.id) }}
                    className="flex items-center gap-2"
                  >
                    <ListTodo className="h-4 w-4" />
                    <span>Projects</span>
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
                          to="/projects"
                          search={{ create: "true", initiativeId: String(initiative.id) }}
                        >
                          <Plus className="h-3 w-3" />
                        </Link>
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      <p>Create Project</p>
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
                      to="/projects/$projectId"
                      params={{ projectId: String(project.id) }}
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
                            <Link
                              to="/projects/$projectId/settings"
                              params={{ projectId: String(project.id) }}
                            >
                              <Settings className="h-3 w-3" />
                            </Link>
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent side="top">
                          <p>Project Settings</p>
                        </TooltipContent>
                      </Tooltip>

                      {/* Mobile: Show three-dot menu */}
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 shrink-0 lg:hidden"
                            aria-label="Project actions"
                          >
                            <MoreVertical className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-48">
                          <DropdownMenuItem asChild>
                            <Link
                              to="/projects/$projectId/settings"
                              params={{ projectId: String(project.id) }}
                            >
                              <Settings className="mr-2 h-4 w-4" />
                              Project Settings
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
    </Collapsible>
  );
};

// Maximum visual indentation depth (children still render, just don't indent further)
const MAX_TAG_INDENT = 3;

interface TagTreeNode {
  segment: string; // The segment name (e.g., "a" for "parent/a")
  fullPath: string; // The full path (e.g., "parent/a")
  tag: TagType | null; // The actual tag at this node, if it exists
  children: TagTreeNode[];
}

interface TagBrowserProps {
  tags: TagType[];
  isLoading: boolean;
}

const TagBrowser = ({ tags, isLoading }: TagBrowserProps) => {
  // Build a tree structure from flat tag list
  const tagTree = useMemo(() => {
    const tagsByPath = new Map<string, TagType>();
    tags.forEach((tag) => tagsByPath.set(tag.name, tag));

    const root: TagTreeNode[] = [];

    // Helper to find or create a node at a given path
    const getOrCreateNode = (
      nodes: TagTreeNode[],
      segments: string[],
      currentPath: string
    ): TagTreeNode => {
      const segment = segments[0];
      let node = nodes.find((n) => n.segment === segment);

      if (!node) {
        node = {
          segment,
          fullPath: currentPath,
          tag: tagsByPath.get(currentPath) ?? null,
          children: [],
        };
        nodes.push(node);
      }

      return node;
    };

    // Insert each tag into the tree
    tags.forEach((tag) => {
      const segments = tag.name.split("/");

      // Build path progressively and ensure all ancestor nodes exist
      let currentNodes = root;
      let currentPath = "";

      segments.forEach((segment, index) => {
        currentPath = index === 0 ? segment : `${currentPath}/${segment}`;
        const node = getOrCreateNode(currentNodes, [segment], currentPath);

        // Update the tag reference if this is the exact path
        if (currentPath === tag.name) {
          node.tag = tag;
        }

        currentNodes = node.children;
      });
    });

    // Sort nodes recursively
    const sortNodes = (nodes: TagTreeNode[]): TagTreeNode[] => {
      return nodes
        .map((node) => ({
          ...node,
          children: sortNodes(node.children),
        }))
        .sort((a, b) => a.segment.localeCompare(b.segment));
    };

    return sortNodes(root);
  }, [tags]);

  if (isLoading) {
    return (
      <div className="space-y-2 px-4">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }

  if (tags.length === 0) {
    return <div className="text-muted-foreground px-4 py-2 text-sm">No tags created yet</div>;
  }

  return (
    <div className="space-y-1">
      {tagTree.map((node) => (
        <TagTreeNodeComponent key={node.fullPath} node={node} depth={0} />
      ))}
    </div>
  );
};

interface TagTreeNodeComponentProps {
  node: TagTreeNode;
  depth: number;
}

const TagTreeNodeComponent = ({ node, depth }: TagTreeNodeComponentProps) => {
  const [isOpen, setIsOpen] = useState(() => {
    try {
      const stored = localStorage.getItem("tag-group-collapsed-states");
      if (stored) {
        const states = JSON.parse(stored) as Record<string, boolean>;
        return states[node.fullPath] ?? false;
      }
    } catch {
      // Ignore parsing errors
    }
    return false;
  });

  useEffect(() => {
    try {
      const stored = localStorage.getItem("tag-group-collapsed-states");
      const states = stored ? (JSON.parse(stored) as Record<string, boolean>) : {};
      states[node.fullPath] = isOpen;
      localStorage.setItem("tag-group-collapsed-states", JSON.stringify(states));
    } catch {
      // Ignore storage errors
    }
  }, [isOpen, node.fullPath]);

  const hasChildren = node.children.length > 0;
  const canExpand = hasChildren;

  // Get color from this node's tag, or first descendant with a tag
  const getNodeColor = (n: TagTreeNode): string | undefined => {
    if (n.tag?.color) return n.tag.color;
    for (const child of n.children) {
      const color = getNodeColor(child);
      if (color) return color;
    }
    return undefined;
  };
  const nodeColor = getNodeColor(node);

  // Count all descendant tags (for display)
  const countDescendants = (n: TagTreeNode): number => {
    let count = 0;
    for (const child of n.children) {
      if (child.tag) count++;
      count += countDescendants(child);
    }
    return count;
  };
  const descendantCount = countDescendants(node);

  // Leaf node (no children) - simple clickable item
  if (!hasChildren) {
    if (!node.tag) return null; // Ghost node with no tag and no children
    return (
      <Link
        to="/tags/$tagId"
        params={{ tagId: String(node.tag.id) }}
        className="hover:bg-accent flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors"
      >
        <span
          className="h-3 w-3 shrink-0 rounded-full"
          style={{ backgroundColor: node.tag.color }}
        />
        <span className="min-w-0 flex-1 truncate">{node.segment}</span>
      </Link>
    );
  }

  // Node with children - collapsible
  return (
    <Collapsible open={isOpen} onOpenChange={canExpand ? setIsOpen : undefined}>
      <div className="flex items-center">
        {canExpand ? (
          <CollapsibleTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0"
              aria-label={isOpen ? "Collapse" : "Expand"}
            >
              <CircleChevronRight
                className={cn("h-4 w-4 transition-transform", isOpen && "rotate-90")}
                style={{ color: nodeColor || undefined }}
              />
            </Button>
          </CollapsibleTrigger>
        ) : (
          <span className="flex h-7 w-7 shrink-0 items-center justify-center">
            <span
              className="h-3 w-3 rounded-full"
              style={{ backgroundColor: nodeColor || undefined }}
            />
          </span>
        )}
        {node.tag ? (
          <Link
            to="/tags/$tagId"
            params={{ tagId: String(node.tag.id) }}
            className="hover:bg-accent flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-1.5 text-sm transition-colors"
          >
            <span className="min-w-0 flex-1 truncate font-medium">{node.segment}</span>
            <span className="text-muted-foreground shrink-0 text-xs">{descendantCount}</span>
          </Link>
        ) : (
          <span className="flex min-w-0 flex-1 items-center gap-2 px-1 py-1.5 text-sm">
            <span className="min-w-0 flex-1 truncate font-medium">{node.segment}</span>
            <span className="text-muted-foreground shrink-0 text-xs">{descendantCount}</span>
          </span>
        )}
      </div>
      {canExpand && (
        <CollapsibleContent
          className={cn("space-y-0.5 border-l pl-2", depth < MAX_TAG_INDENT && "ml-3")}
          style={{ borderColor: nodeColor || undefined }}
        >
          {node.children.map((child) => (
            <TagTreeNodeComponent key={child.fullPath} node={child} depth={depth + 1} />
          ))}
        </CollapsibleContent>
      )}
    </Collapsible>
  );
};
