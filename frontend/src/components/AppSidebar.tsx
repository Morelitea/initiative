import { useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { useAutoCloseSidebar } from "@/hooks/useAutoCloseSidebar";
import {
  Settings,
  Plus,
  FileText,
  Star,
  ChevronRight,
  Users,
  ListTodo,
  MoreVertical,
} from "lucide-react";

import { apiClient } from "@/api/client";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { GuildSidebar } from "@/components/guilds/GuildSidebar";
import { ModeToggle } from "@/components/ModeToggle";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { cn } from "@/lib/utils";
import { useIsMobile } from "@/hooks/use-mobile";
import type { Initiative, Project } from "@/types/api";

export const AppSidebar = () => {
  const { user, logout } = useAuth();
  const { activeGuild, activeGuildId } = useGuilds();
  const isMobile = useIsMobile();
  const location = useLocation();

  // Auto-close sidebar on mobile after navigation
  useAutoCloseSidebar();

  const isGuildAdmin = user?.role === "admin" || activeGuild?.role === "admin";
  const isSuperUser = user?.id === 1;

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
  });

  const projectsQuery = useQuery<Project[]>({
    queryKey: ["projects", activeGuildId],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/");
      return response.data;
    },
    enabled: Boolean(activeGuild),
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

  const userDisplayName = user?.full_name ?? user?.email ?? "User";
  const userEmail = user?.email ?? "";
  const userInitials =
    userDisplayName
      .split(/\s+/)
      .map((part) => part.charAt(0).toUpperCase())
      .join("")
      .slice(0, 2) || "U";
  const avatarSrc = user?.avatar_url || user?.avatar_base64 || null;

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

            <SidebarContent className="flex-1 overflow-x-hidden overflow-y-auto">
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
                            <SidebarMenuButton asChild isActive={project.id === activeProjectId}>
                              <Link
                                to={`/projects/${project.id}`}
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
                      {visibleInitiatives.map((initiative) => (
                        <InitiativeSection
                          key={initiative.id}
                          initiative={initiative}
                          projects={projectsByInitiative.get(initiative.id) ?? []}
                          documentCount={documentCountsByInitiative.get(initiative.id) ?? 0}
                          isGuildAdmin={isGuildAdmin}
                          activeProjectId={activeProjectId}
                        />
                      ))}
                    </div>
                  )}

                  {isGuildAdmin && (
                    <SidebarMenu>
                      <SidebarMenuItem>
                        <SidebarMenuButton asChild size="sm">
                          <Link to="/initiatives?create=true">
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
                    <Link to="/profile">User Settings</Link>
                  </DropdownMenuItem>
                  {isGuildAdmin && (
                    <DropdownMenuItem asChild>
                      <Link to="/settings/guild">Guild Settings</Link>
                    </DropdownMenuItem>
                  )}
                  {isSuperUser && (
                    <DropdownMenuItem asChild>
                      <Link to="/settings/admin">Platform Settings</Link>
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
            <div className="text-muted-foreground border-t px-3 py-2 text-center text-xs">
              v{__APP_VERSION__}
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
  isGuildAdmin: boolean;
  activeProjectId: number | null;
}

const InitiativeSection = ({
  initiative,
  projects,
  documentCount,
  isGuildAdmin,
  activeProjectId,
}: InitiativeSectionProps) => {
  const [isOpen, setIsOpen] = useState(true);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <div className="group/initiative flex min-w-0 items-center gap-1">
        <div className="flex min-w-0 flex-1 items-center">
          <Button
            variant="ghost"
            className="hover:bg-accent min-w-0 flex-1 justify-start gap-2 px-2 py-1.5 text-sm font-medium"
            asChild
          >
            <Link to={`/initiatives/${initiative.id}`} className="flex min-w-0 items-center gap-2">
              <InitiativeColorDot color={initiative.color} className="h-2 w-2 shrink-0" />
              <span className="min-w-0 flex-1 truncate text-left">{initiative.name}</span>
            </Link>
          </Button>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0">
              <ChevronRight
                className={cn(
                  "text-muted-foreground h-4 w-4 transition-transform",
                  isOpen && "rotate-90"
                )}
              />
            </Button>
          </CollapsibleTrigger>
        </div>
        {isGuildAdmin && (
          <>
            {/* Desktop: Show hover-reveal settings button */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="hidden h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover/initiative:opacity-100 lg:flex"
                  asChild
                >
                  <Link to={`/initiatives/${initiative.id}/settings`}>
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
                  <Link to={`/initiatives/${initiative.id}/settings`}>
                    <Settings className="mr-2 h-4 w-4" />
                    Initiative Settings
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link to={`/documents?create=true&initiativeId=${initiative.id}`}>
                    <Plus className="mr-2 h-4 w-4" />
                    Create Document
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link to={`/projects?create=true&initiativeId=${initiative.id}`}>
                    <Plus className="mr-2 h-4 w-4" />
                    Create Project
                  </Link>
                </DropdownMenuItem>
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
          <SidebarMenuItem>
            <div className="group/documents flex w-full min-w-0 items-center gap-1">
              <SidebarMenuButton asChild size="sm" className="min-w-0 flex-1">
                <Link
                  to={`/documents?initiativeId=${initiative.id}`}
                  className="flex items-center gap-2"
                >
                  <FileText className="h-4 w-4" />
                  <span>Documents</span>
                  <span className="text-muted-foreground text-xs">{documentCount}</span>
                </Link>
              </SidebarMenuButton>
              {isGuildAdmin && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="hidden h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover/documents:opacity-100 lg:flex"
                      asChild
                    >
                      <Link to={`/documents?create=true&initiativeId=${initiative.id}`}>
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

          {/* Projects Link */}
          <SidebarMenuItem>
            <div className="group/projects flex w-full min-w-0 items-center gap-1">
              <SidebarMenuButton asChild size="sm" className="min-w-0 flex-1">
                <Link
                  to={`/projects?initiativeId=${initiative.id}`}
                  className="flex items-center gap-2"
                >
                  <ListTodo className="h-4 w-4" />
                  <span>Projects</span>
                  <span className="text-muted-foreground text-xs">{projects.length}</span>
                </Link>
              </SidebarMenuButton>
              {isGuildAdmin && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="hidden h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover/projects:opacity-100 lg:flex"
                      asChild
                    >
                      <Link to={`/projects?create=true&initiativeId=${initiative.id}`}>
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

          {/* Projects List */}
          {projects.map((project) => (
            <SidebarMenuItem key={project.id}>
              <div className="group/project flex w-full min-w-0 items-center gap-1">
                <SidebarMenuButton
                  asChild
                  size="sm"
                  className="min-w-0 flex-1"
                  isActive={project.id === activeProjectId}
                >
                  <Link to={`/projects/${project.id}`} className="flex min-w-0 items-center gap-2">
                    {project.icon ? (
                      <span className="shrink-0 text-base">{project.icon}</span>
                    ) : null}
                    <span className="min-w-0 flex-1 truncate">{project.name}</span>
                  </Link>
                </SidebarMenuButton>
                {/* Desktop: Show hover-reveal settings button */}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="hidden h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover/project:opacity-100 lg:flex"
                      asChild
                    >
                      <Link to={`/projects/${project.id}/settings`}>
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
                      <Link to={`/projects/${project.id}/settings`}>
                        <Settings className="mr-2 h-4 w-4" />
                        Project Settings
                      </Link>
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </CollapsibleContent>
    </Collapsible>
  );
};
