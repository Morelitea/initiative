import { useCallback, useMemo, useState } from "react";
import { Link, useLocation } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useAutoCloseSidebar } from "@/hooks/useAutoCloseSidebar";
import {
  Settings,
  Plus,
  ScrollText,
  Star,
  Users,
  ListTodo,
  Tag,
  ChevronsDownUp,
  ChevronsUpDown,
  GalleryHorizontalEnd,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { GuildSidebar } from "@/components/guilds/GuildSidebar";
import { HomeSidebarContent } from "@/components/HomeSidebarContent";
import { InitiativeSection } from "@/components/sidebar/InitiativeSection";
import { TagBrowser } from "@/components/sidebar/TagBrowser";
import { SidebarUserFooter } from "@/components/sidebar/SidebarUserFooter";
import { useAuth } from "@/hooks/useAuth";
import { useAllDocumentIds } from "@/hooks/useDocuments";
import { useGuilds } from "@/hooks/useGuilds";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useProjects, useFavoriteProjects } from "@/hooks/useProjects";
import { useDockerHubVersion, compareVersions } from "@/hooks/useDockerHubVersion";
import { useTags } from "@/hooks/useTags";
import { useQueuesList } from "@/hooks/useQueues";
import { getItem, setItem } from "@/lib/storage";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { useIsMobile } from "@/hooks/use-mobile";
import { guildPath } from "@/lib/guildUrl";
import type { InitiativeRead, ProjectRead } from "@/api/generated/initiativeAPI.schemas";

export const AppSidebar = () => {
  const { user, logout } = useAuth();
  const { activeGuild, activeGuildId } = useGuilds();
  const isMobile = useIsMobile();
  const location = useLocation();
  const { t } = useTranslation("nav");

  // Auto-close sidebar on mobile after navigation
  useAutoCloseSidebar();

  // Guild admin check is based on guild membership role only (independent from platform role)
  const isGuildAdmin = activeGuild?.role === "admin";
  // Platform admins can access platform settings (separate from guild admin role)
  const isPlatformAdmin = user?.role === "admin";

  // Determine sidebar mode from route
  const isGuildRoute = location.pathname.startsWith("/g/");

  // Extract active project ID from URL (support both old and new URL patterns)
  const activeProjectId = useMemo(() => {
    const match =
      location.pathname.match(/^\/g\/\d+\/projects\/(\d+)/) ||
      location.pathname.match(/^\/projects\/(\d+)/);
    return match ? parseInt(match[1], 10) : null;
  }, [location.pathname]);

  // Helper to create guild-scoped paths
  const gp = (path: string) => (activeGuildId ? guildPath(activeGuildId, path) : path);

  const initiativesQuery = useInitiatives({ enabled: Boolean(activeGuild), staleTime: 60_000 });

  const projectsQuery = useProjects(undefined, {
    enabled: Boolean(activeGuild),
    staleTime: 60_000,
  });

  const favoritesQuery = useFavoriteProjects({
    enabled: activeGuildId !== null,
    staleTime: 60_000,
  });

  const documentsQuery = useAllDocumentIds({ enabled: Boolean(activeGuild), staleTime: 60_000 });

  const projectsByInitiative = useMemo(() => {
    const map = new Map<number, ProjectRead[]>();
    const projects = projectsQuery.data?.items ?? [];
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

  // Fetch queues for counts (lightweight list query)
  const queuesQuery = useQueuesList(
    { page: 1, page_size: 100 },
    { enabled: Boolean(activeGuild), staleTime: 60_000 }
  );

  const queueCountsByInitiative = useMemo(() => {
    const map = new Map<number, number>();
    const queues = queuesQuery.data?.items ?? [];
    queues.forEach((queue) => {
      const count = map.get(queue.initiative_id) ?? 0;
      map.set(queue.initiative_id, count + 1);
    });
    return map;
  }, [queuesQuery.data]);

  const visibleInitiatives = useMemo(() => {
    if (!user) {
      return [];
    }
    const source = Array.isArray(initiativesQuery.data) ? initiativesQuery.data : [];
    if (isGuildAdmin) {
      return source.slice().sort((a, b) => a.name.localeCompare(b.name));
    }
    const membershipFiltered = source.filter((initiative) =>
      initiative.members.some((member) => member.user.id === user.id)
    );
    return membershipFiltered.sort((a, b) => a.name.localeCompare(b.name));
  }, [initiativesQuery.data, user, isGuildAdmin]);

  // Check if user can manage a specific initiative
  const canManageInitiative = useCallback(
    (initiative: InitiativeRead): boolean => {
      if (isGuildAdmin) {
        return true;
      }
      if (!user) {
        return false;
      }
      return initiative.members.some(
        (member) => member.user.id === user.id && member.role === "project_manager"
      );
    },
    [user, isGuildAdmin]
  );

  // Get user's permissions for an initiative
  const getUserPermissions = useCallback(
    (initiative: InitiativeRead) => {
      if (!user) {
        return {
          canViewDocs: true,
          canViewProjects: true,
          canViewQueues: true,
          canCreateDocs: false,
          canCreateProjects: false,
          canCreateQueues: false,
        };
      }
      // Guild admins have all permissions
      if (isGuildAdmin) {
        return {
          canViewDocs: true,
          canViewProjects: true,
          canViewQueues: true,
          canCreateDocs: true,
          canCreateProjects: true,
          canCreateQueues: true,
        };
      }
      const membership = initiative.members.find((m) => m.user.id === user.id);
      if (!membership) {
        return {
          canViewDocs: true,
          canViewProjects: true,
          canViewQueues: true,
          canCreateDocs: false,
          canCreateProjects: false,
          canCreateQueues: false,
        };
      }
      return {
        canViewDocs: membership.can_view_docs ?? true,
        canViewProjects: membership.can_view_projects ?? true,
        canViewQueues: membership.can_view_queues ?? false,
        canCreateDocs: membership.can_create_docs ?? false,
        canCreateProjects: membership.can_create_projects ?? false,
        canCreateQueues: membership.can_create_queues ?? false,
      };
    },
    [user, isGuildAdmin]
  );

  const userDisplayName = user?.full_name ?? user?.email ?? "User";
  const userEmail = user?.email ?? "";
  const userInitials = useMemo(
    () =>
      userDisplayName
        .split(/\s+/)
        .map((part) => part.charAt(0).toUpperCase())
        .join("")
        .slice(0, 2) || "U",
    [userDisplayName]
  );
  const avatarSrc = resolveUploadUrl(user?.avatar_url) || user?.avatar_base64 || null;

  // Fetch tags for the tag browser
  const tagsQuery = useTags();

  // Collapse/expand all for initiatives
  const [initiativeCollapseKey, setInitiativeCollapseKey] = useState(0);
  const collapseAllInitiatives = useCallback(() => {
    const states: Record<number, boolean> = {};
    for (const init of visibleInitiatives) {
      states[init.id] = false;
    }
    setItem("initiative-collapsed-states", JSON.stringify(states));
    setInitiativeCollapseKey((k) => k + 1);
  }, [visibleInitiatives]);
  const expandAllInitiatives = useCallback(() => {
    const states: Record<number, boolean> = {};
    for (const init of visibleInitiatives) {
      states[init.id] = true;
    }
    setItem("initiative-collapsed-states", JSON.stringify(states));
    setInitiativeCollapseKey((k) => k + 1);
  }, [visibleInitiatives]);
  const allInitiativesCollapsed = useMemo(() => {
    try {
      const stored = getItem("initiative-collapsed-states");
      if (!stored) return false;
      const states = JSON.parse(stored) as Record<number, boolean>;
      return (
        visibleInitiatives.length > 0 && visibleInitiatives.every((i) => states[i.id] === false)
      );
    } catch {
      return false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleInitiatives, initiativeCollapseKey]);

  // Collapse/expand all for tags
  const [tagCollapseKey, setTagCollapseKey] = useState(0);
  const collapseAllTags = useCallback(() => {
    setItem("tag-group-collapsed-states", JSON.stringify({}));
    setTagCollapseKey((k) => k + 1);
  }, []);
  const expandAllTags = useCallback(() => {
    const tags = tagsQuery.data ?? [];
    const states: Record<string, boolean> = {};
    for (const tag of tags) {
      if (tag.name.includes("/")) {
        // Expand all parent segments
        const parts = tag.name.split("/");
        let path = "";
        for (const part of parts.slice(0, -1)) {
          path = path ? `${path}/${part}` : part;
          states[path] = true;
        }
      }
    }
    setItem("tag-group-collapsed-states", JSON.stringify(states));
    setTagCollapseKey((k) => k + 1);
  }, [tagsQuery.data]);

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
          <GuildSidebar isHomeMode={!isGuildRoute} />
          <div className="flex max-w-full min-w-0 flex-1 flex-col overflow-hidden border-r">
            {!isGuildRoute ? (
              <HomeSidebarContent />
            ) : (
              <>
                <SidebarHeader className="border-b">
                  <div className="flex min-w-0 items-center justify-between gap-2 p-4">
                    <h2 className="min-w-0 flex-1 truncate text-lg font-semibold">
                      {activeGuild?.name ?? t("selectGuild")}
                    </h2>
                    {activeGuild && isGuildAdmin && (
                      <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" asChild>
                        <Link to={gp("/settings")} aria-label={t("guildSettings")}>
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
                      {t("initiatives")}
                    </TabsTrigger>
                    <TabsTrigger value="tags" className="flex-1 text-xs">
                      <Tag className="mr-2 h-3.5 w-3.5" />
                      {t("tags")}
                    </TabsTrigger>
                  </TabsList>
                  {/* </div> */}

                  <TabsContent value="initiatives" className="mt-0 flex-1 overflow-hidden">
                    <SidebarContent className="h-full overflow-x-hidden overflow-y-auto">
                      {/* Favorites Section */}
                      {Array.isArray(favoritesQuery?.data) && favoritesQuery.data.length > 0 && (
                        <>
                          <SidebarGroup>
                            <SidebarGroupLabel className="flex items-center gap-2 py-2">
                              <Star className="h-4 w-4" />
                              {t("favorites")}
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
                                        to={gp(`/projects/${project.id}`)}
                                        className="flex min-w-0 items-center gap-2"
                                      >
                                        {project.icon ? (
                                          <span className="shrink-0 text-lg">{project.icon}</span>
                                        ) : null}
                                        <span className="min-w-0 flex-1 truncate">
                                          {project.name}
                                        </span>
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

                      {/* All Projects & All Documents */}
                      {activeGuild && (
                        <>
                          <SidebarGroup>
                            <SidebarGroupContent>
                              <SidebarMenu>
                                <SidebarMenuItem>
                                  <SidebarMenuButton asChild>
                                    <Link to={gp("/projects")} className="flex items-center gap-2">
                                      <ListTodo className="h-4 w-4" />
                                      <span>{t("allProjects")}</span>
                                    </Link>
                                  </SidebarMenuButton>
                                </SidebarMenuItem>
                                <SidebarMenuItem>
                                  <SidebarMenuButton asChild>
                                    <Link to={gp("/documents")} className="flex items-center gap-2">
                                      <ScrollText className="h-4 w-4" />
                                      <span>{t("allDocuments")}</span>
                                    </Link>
                                  </SidebarMenuButton>
                                </SidebarMenuItem>
                                <SidebarMenuItem>
                                  <SidebarMenuButton asChild>
                                    <Link to={gp("/queues")} className="flex items-center gap-2">
                                      <GalleryHorizontalEnd className="h-4 w-4" />
                                      <span>{t("allQueues")}</span>
                                    </Link>
                                  </SidebarMenuButton>
                                </SidebarMenuItem>
                              </SidebarMenu>
                            </SidebarGroupContent>
                          </SidebarGroup>
                          <SidebarSeparator />
                        </>
                      )}

                      {/* Initiatives Section */}
                      <SidebarGroup>
                        <SidebarGroupLabel className="flex items-center gap-2 py-2">
                          <Users className="h-4 w-4" />
                          <span className="flex-1">{t("initiatives")}</span>
                          {visibleInitiatives.length > 0 && (
                            <Tooltip delayDuration={300}>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-5 w-5 shrink-0"
                                  onClick={
                                    allInitiativesCollapsed
                                      ? expandAllInitiatives
                                      : collapseAllInitiatives
                                  }
                                  aria-label={
                                    allInitiativesCollapsed ? t("expandAll") : t("collapseAll")
                                  }
                                >
                                  {allInitiativesCollapsed ? (
                                    <ChevronsUpDown className="h-3.5 w-3.5" />
                                  ) : (
                                    <ChevronsDownUp className="h-3.5 w-3.5" />
                                  )}
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent side="bottom">
                                <p>{allInitiativesCollapsed ? t("expandAll") : t("collapseAll")}</p>
                              </TooltipContent>
                            </Tooltip>
                          )}
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
                              {t("noInitiativesAvailable")}
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
                                    documentCount={
                                      documentCountsByInitiative.get(initiative.id) ?? 0
                                    }
                                    canManageInitiative={canManageInitiative(initiative)}
                                    activeProjectId={activeProjectId}
                                    userId={user?.id}
                                    canViewDocs={permissions.canViewDocs}
                                    canViewProjects={permissions.canViewProjects}
                                    canViewQueues={permissions.canViewQueues}
                                    canCreateDocs={permissions.canCreateDocs}
                                    canCreateProjects={permissions.canCreateProjects}
                                    canCreateQueues={permissions.canCreateQueues}
                                    queueCount={queueCountsByInitiative.get(initiative.id) ?? 0}
                                    activeGuildId={activeGuildId}
                                    collapseKey={initiativeCollapseKey}
                                  />
                                );
                              })}
                            </div>
                          )}

                          {isGuildAdmin && (
                            <SidebarMenu>
                              <SidebarMenuItem>
                                <SidebarMenuButton asChild size="sm">
                                  <Link to={gp("/initiatives")} search={{ create: "true" }}>
                                    <Plus className="h-4 w-4" />
                                    <span>{t("addInitiative")}</span>
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
                          <Tag className="h-4 w-4" />
                          <span className="flex-1">{t("tags")}</span>
                          {(tagsQuery.data ?? []).length > 0 && (
                            <Tooltip delayDuration={300}>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-5 w-5 shrink-0"
                                  onClick={expandAllTags}
                                  aria-label={t("expandAll")}
                                >
                                  <ChevronsUpDown className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent side="bottom">
                                <p>{t("expandAll")}</p>
                              </TooltipContent>
                            </Tooltip>
                          )}
                          {(tagsQuery.data ?? []).length > 0 && (
                            <Tooltip delayDuration={300}>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-5 w-5 shrink-0"
                                  onClick={collapseAllTags}
                                  aria-label={t("collapseAll")}
                                >
                                  <ChevronsDownUp className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent side="bottom">
                                <p>{t("collapseAll")}</p>
                              </TooltipContent>
                            </Tooltip>
                          )}
                        </SidebarGroupLabel>
                        <SidebarGroupContent>
                          <TagBrowser
                            tags={tagsQuery.data ?? []}
                            isLoading={tagsQuery.isLoading}
                            activeGuildId={activeGuildId}
                            collapseKey={tagCollapseKey}
                          />
                        </SidebarGroupContent>
                      </SidebarGroup>
                    </SidebarContent>
                  </TabsContent>
                </Tabs>
              </>
            )}
          </div>
        </div>

        <SidebarUserFooter
          userDisplayName={userDisplayName}
          userEmail={userEmail}
          userInitials={userInitials}
          avatarSrc={avatarSrc}
          isGuildAdmin={isGuildAdmin}
          isPlatformAdmin={isPlatformAdmin}
          activeGuildId={activeGuildId}
          hasUser={Boolean(user)}
          currentVersion={currentVersion}
          latestVersion={latestVersion ?? null}
          hasUpdate={Boolean(hasUpdate)}
          isLoadingVersion={isLoadingVersion}
          onLogout={logout}
        />
      </div>
    </Sidebar>
  );
};
