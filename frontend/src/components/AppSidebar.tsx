import { Link, useLocation } from "@tanstack/react-router";
import {
  ChevronsDownUp,
  ChevronsUpDown,
  ListTodo,
  Plus,
  ScrollText,
  Settings,
  Star,
  Tag,
  Users,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { GuildSidebar } from "@/components/guilds/GuildSidebar";
import { HomeSidebarContent } from "@/components/sidebar/HomeSidebarContent";
import { InitiativeSection } from "@/components/sidebar/InitiativeSection";
import { SidebarUserFooter } from "@/components/sidebar/SidebarUserFooter";
import { TagBrowser } from "@/components/sidebar/TagBrowser";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
} from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useIsMobile } from "@/hooks/use-mobile";
import { useAuth } from "@/hooks/useAuth";
import { useAutoCloseSidebar } from "@/hooks/useAutoCloseSidebar";
import { useCounterGroupsList } from "@/hooks/useCounters";
import { compareVersions, useDockerHubVersion } from "@/hooks/useDockerHubVersion";
import { useAllDocumentIds } from "@/hooks/useDocuments";
import { useGuilds } from "@/hooks/useGuilds";
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useFavoriteProjects, useProjects } from "@/hooks/useProjects";
import { useQueuesList } from "@/hooks/useQueues";
import { useTags } from "@/hooks/useTags";
import { guildPath } from "@/lib/guildUrl";
import { getInitials } from "@/lib/initials";
import { obfuscateEmail } from "@/lib/obfuscateEmail";
import { canAccessAdminDashboard, canManagePlatformConfig } from "@/lib/permissions";
import { getItem, setItem } from "@/lib/storage";
import { resolveUploadUrl } from "@/lib/uploadUrl";

export const AppSidebar = () => {
  const { user, logout } = useAuth();
  const { activeGuild, activeGuildId } = useGuilds();
  const isMobile = useIsMobile();
  const location = useLocation();
  const { t } = useTranslation("nav");

  // Auto-close sidebar on mobile after navigation
  useAutoCloseSidebar();

  // Guild admin check is based on guild membership role only (independent from platform role).
  // Used for guild-settings affordances. Initiative visibility/permissions
  // (incl. PAM grants + platform data.bypass) come from useInitiativeAccess.
  const isGuildAdmin = activeGuild?.role === "admin";
  const { filterVisible, permissionsFor, canManage } = useInitiativeAccess();
  // Two separate platform areas: config (Platform settings) vs operational
  // (Admin dashboard). Each surfaced independently per capability.
  const showPlatformSettings = canManagePlatformConfig(user);
  const showAdminDashboard = canAccessAdminDashboard(user);

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

  // The guild tree (initiatives/projects/documents/queues/counters/tags) is
  // only rendered on /g/ routes, and only there does the server-held guild
  // context line up with it — on personal pages these guild-scoped queries
  // would 409 (no context) and cache errors that linger as zeroed counts.
  // Gate them all on actually being in the guild UI.
  const guildTreeEnabled = Boolean(activeGuild) && isGuildRoute;

  const initiativesQuery = useInitiatives({ enabled: guildTreeEnabled, staleTime: 60_000 });

  const projectsQuery = useProjects(undefined, {
    enabled: guildTreeEnabled,
    staleTime: 60_000,
  });

  const favoritesQuery = useFavoriteProjects({
    enabled: guildTreeEnabled,
    staleTime: 60_000,
  });

  const documentsQuery = useAllDocumentIds({ enabled: guildTreeEnabled, staleTime: 60_000 });

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
    { enabled: guildTreeEnabled, staleTime: 60_000 }
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

  // Fetch counter groups for counts
  const counterGroupsQuery = useCounterGroupsList(
    { page: 1, page_size: 100 },
    { enabled: guildTreeEnabled, staleTime: 60_000 }
  );
  const counterGroupCountsByInitiative = useMemo(() => {
    const map = new Map<number, number>();
    const groups = counterGroupsQuery.data?.items ?? [];
    groups.forEach((group) => {
      const count = map.get(group.initiative_id) ?? 0;
      map.set(group.initiative_id, count + 1);
    });
    return map;
  }, [counterGroupsQuery.data]);

  const visibleInitiatives = useMemo(
    () => filterVisible(Array.isArray(initiativesQuery.data) ? initiativesQuery.data : []),
    [initiativesQuery.data, filterVisible]
  );

  // Initiative visibility + per-section permissions (membership, PAM grants,
  // platform data.bypass) are centralized in useInitiativeAccess.
  const canManageInitiative = canManage;
  const getUserPermissions = permissionsFor;

  const userDisplayName = user?.full_name ?? (obfuscateEmail(user?.email) || "User");
  const userInitials = useMemo(
    () => getInitials(user?.full_name, user?.email),
    [user?.full_name, user?.email]
  );
  const avatarSrc = resolveUploadUrl(user?.avatar_url) || user?.avatar_base64 || null;

  // Fetch tags for the tag browser
  const tagsQuery = useTags({ enabled: guildTreeEnabled });

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
      <div className="flex h-full w-full min-w-0 max-w-full flex-col">
        <div className="flex min-h-0 max-w-full flex-1">
          <GuildSidebar isHomeMode={!isGuildRoute} />
          <div className="flex min-w-0 max-w-full flex-1 flex-col overflow-hidden border-r">
            {!isGuildRoute ? (
              <HomeSidebarContent />
            ) : (
              <>
                <SidebarHeader
                  className="gap-0 border-b p-0"
                  style={{ paddingTop: "var(--safe-area-inset-top)" }}
                >
                  <div className="flex h-12 min-w-0 items-center justify-between gap-2 px-2.5">
                    <h2 className="min-w-0 flex-1 truncate font-semibold text-lg">
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
                    <ScrollArea className="[&_[data-radix-scroll-area-viewport]>div]:block! h-full">
                      <SidebarContent className="overflow-x-hidden overflow-y-visible">
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
                                      <Link
                                        to={gp("/projects")}
                                        className="flex items-center gap-2"
                                      >
                                        <ListTodo className="h-4 w-4" />
                                        <span>{t("allProjects")}</span>
                                      </Link>
                                    </SidebarMenuButton>
                                  </SidebarMenuItem>
                                  <SidebarMenuItem>
                                    <SidebarMenuButton asChild>
                                      <Link
                                        to={gp("/documents")}
                                        className="flex items-center gap-2"
                                      >
                                        <ScrollText className="h-4 w-4" />
                                        <span>{t("allDocuments")}</span>
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
                                  <p>
                                    {allInitiativesCollapsed ? t("expandAll") : t("collapseAll")}
                                  </p>
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
                              <div className="px-4 py-2 text-muted-foreground text-sm">
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
                                      canViewEvents={permissions.canViewEvents}
                                      canViewAdvancedTool={permissions.canViewAdvancedTool}
                                      canViewCounters={permissions.canViewCounters}
                                      canCreateDocs={permissions.canCreateDocs}
                                      canCreateProjects={permissions.canCreateProjects}
                                      canCreateQueues={permissions.canCreateQueues}
                                      canCreateEvents={permissions.canCreateEvents}
                                      canCreateCounters={permissions.canCreateCounters}
                                      queueCount={queueCountsByInitiative.get(initiative.id) ?? 0}
                                      counterGroupCount={
                                        counterGroupCountsByInitiative.get(initiative.id) ?? 0
                                      }
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
                    </ScrollArea>
                  </TabsContent>

                  <TabsContent value="tags" className="mt-0 flex-1 overflow-hidden">
                    <ScrollArea className="[&_[data-radix-scroll-area-viewport]>div]:block! h-full">
                      <SidebarContent className="overflow-x-hidden overflow-y-visible">
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
                    </ScrollArea>
                  </TabsContent>
                </Tabs>
              </>
            )}
          </div>
        </div>

        <SidebarUserFooter
          userId={user?.id ?? null}
          userDisplayName={userDisplayName}
          userInitials={userInitials}
          avatarSrc={avatarSrc}
          isGuildAdmin={isGuildAdmin}
          canManagePlatformConfig={showPlatformSettings}
          canAccessAdminDashboard={showAdminDashboard}
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
