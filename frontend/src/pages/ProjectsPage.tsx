import { HTMLAttributes, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import {
  DndContext,
  DragEndEvent,
  MouseSensor,
  TouchSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { LayoutGrid, ScrollText, Archive, List, Plus, Pin as PinIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  useProjects,
  useTemplateProjects,
  useArchivedProjects,
  useUpdateProject,
  useUnarchiveProject,
  useReorderProjects,
} from "@/hooks/useProjects";
import { useInitiatives } from "@/hooks/useInitiatives";
import { invalidateAllProjects } from "@/api/query-keys";
import { getItem, setItem } from "@/lib/storage";
import { useGuildPath } from "@/lib/guildUrl";
import { Markdown } from "@/components/Markdown";
import { PullToRefresh } from "@/components/PullToRefresh";
import { ProjectCardLink, ProjectRowLink } from "@/components/projects/ProjectPreview";
import { CreateProjectDialog } from "@/components/projects/CreateProjectDialog";
import { ProjectsFilterBar } from "@/components/projects/ProjectsFilterBar";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import {
  useMyInitiativePermissions,
  canCreate as canCreatePermission,
} from "@/hooks/useInitiativeRoles";
import type { ProjectRead, TagRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { useTags } from "@/hooks/useTags";

const INITIATIVE_FILTER_ALL = "all";
const PROJECT_SORT_KEY = "project:list:sort";
const PROJECT_SEARCH_KEY = "project:list:search";
const PROJECT_VIEW_KEY = "project:list:view-mode";
const PROJECT_TAG_FILTERS_KEY = "project:list:tag-filters";
const getDefaultFiltersVisibility = () => {
  if (typeof window === "undefined") {
    return true;
  }
  return window.matchMedia("(min-width: 640px)").matches;
};

type ProjectsViewProps = {
  fixedInitiativeId?: number;
  fixedTagIds?: number[];
  canCreate?: boolean;
};

export const ProjectsView = ({ fixedInitiativeId, fixedTagIds, canCreate }: ProjectsViewProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const { user } = useAuth();
  const { activeGuildId } = useGuilds();
  const gp = useGuildPath();
  const searchParams = useSearch({ strict: false }) as { create?: string; initiativeId?: string };
  const router = useRouter();
  const lockedInitiativeId = typeof fixedInitiativeId === "number" ? fixedInitiativeId : null;

  const handleRefresh = useCallback(async () => {
    await invalidateAllProjects();
  }, []);
  const claimedManagedInitiatives = useMemo(
    () =>
      user?.initiative_roles?.filter((assignment) => assignment.role === "project_manager") ?? [],
    [user]
  );
  const hasClaimedManagerRole = claimedManagedInitiatives.length > 0;
  const [initiativeId, setInitiativeId] = useState<string | null>(null);
  const [isComposerOpen, setIsComposerOpen] = useState(false);
  const isClosingComposer = useRef(false);

  // Open create dialog when ?create=true is in URL
  useEffect(() => {
    const shouldCreate = searchParams.create === "true";
    const urlInitiativeId = searchParams.initiativeId;

    if (shouldCreate && !isComposerOpen && !isClosingComposer.current) {
      setIsComposerOpen(true);
      if (urlInitiativeId) {
        setInitiativeId(urlInitiativeId);
      }
    }
    // Reset the closing flag once URL no longer has create=true
    if (!shouldCreate) {
      isClosingComposer.current = false;
    }
  }, [searchParams, isComposerOpen]);
  const [searchQuery, setSearchQuery] = useState<string>(() => {
    return getItem(PROJECT_SEARCH_KEY) ?? "";
  });
  const [sortMode, setSortMode] = useState<
    "custom" | "updated" | "created" | "alphabetical" | "recently_viewed"
  >(() => {
    const stored = getItem(PROJECT_SORT_KEY);
    if (
      stored === "custom" ||
      stored === "updated" ||
      stored === "created" ||
      stored === "alphabetical" ||
      stored === "recently_viewed"
    ) {
      return stored;
    }
    return "custom";
  });
  const [customOrder, setCustomOrder] = useState<number[]>([]);
  const updateProjectMutation = useUpdateProject();
  const removeTemplate = {
    mutate: (projectId: number) =>
      updateProjectMutation.mutate({ projectId, data: { is_template: false } }),
    isPending: updateProjectMutation.isPending,
  };

  const [initiativeFilter, setInitiativeFilter] = useState<string>(
    lockedInitiativeId ? String(lockedInitiativeId) : INITIATIVE_FILTER_ALL
  );
  // Parse the filtered initiative ID for permission checks
  const filteredInitiativeId =
    initiativeFilter !== INITIATIVE_FILTER_ALL ? Number(initiativeFilter) : null;
  const { data: filteredInitiativePermissions } = useMyInitiativePermissions(
    !lockedInitiativeId && filteredInitiativeId ? filteredInitiativeId : null
  );
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const lastConsumedFilterParams = useRef<string>("");
  const prevGuildIdRef = useRef<number | null>(activeGuildId);

  // Check for query params to filter by initiative (consume once)
  useEffect(() => {
    const urlInitiativeId = searchParams.initiativeId;
    const paramKey = urlInitiativeId || "";

    if (urlInitiativeId && !lockedInitiativeId && paramKey !== lastConsumedFilterParams.current) {
      lastConsumedFilterParams.current = paramKey;
      setInitiativeFilter(urlInitiativeId);
      // Also set as default for create dialog
      setInitiativeId(urlInitiativeId);
    }
  }, [searchParams, lockedInitiativeId]);

  useEffect(() => {
    if (lockedInitiativeId) {
      const lockedValue = String(lockedInitiativeId);
      setInitiativeFilter((prev) => (prev === lockedValue ? prev : lockedValue));
      // Also set as default for create dialog
      setInitiativeId(lockedValue);
    }
  }, [lockedInitiativeId]);

  // Reset initiative filter when guild changes (initiative IDs are guild-specific)
  useEffect(() => {
    const prevGuildId = prevGuildIdRef.current;
    prevGuildIdRef.current = activeGuildId;
    // Only reset if guild actually changed (not on initial mount)
    if (prevGuildId !== null && prevGuildId !== activeGuildId && !lockedInitiativeId) {
      setInitiativeFilter(INITIATIVE_FILTER_ALL);
      setInitiativeId("");
      lastConsumedFilterParams.current = "";
    }
  }, [activeGuildId, lockedInitiativeId]);

  const unarchiveProject = useUnarchiveProject();

  const [viewMode, setViewMode] = useState<"grid" | "list">(() => {
    const stored = getItem(PROJECT_VIEW_KEY);
    return stored === "list" || stored === "grid" ? stored : "grid";
  });
  const [tabValue, setTabValue] = useState<"active" | "templates" | "archive">("active");
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);
  const [tagFilters, setTagFilters] = useState<number[]>(() => {
    if (fixedTagIds) return fixedTagIds;
    const stored = getItem(PROJECT_TAG_FILTERS_KEY);
    if (!stored) return [];
    try {
      const parsed = JSON.parse(stored);
      return Array.isArray(parsed) ? parsed.filter(Number.isFinite) : [];
    } catch {
      return [];
    }
  });

  // Sync tagFilters when fixedTagIds prop changes (e.g. navigating between tag detail pages)
  useEffect(() => {
    if (fixedTagIds) {
      setTagFilters(fixedTagIds);
    }
  }, [fixedTagIds]);

  const { data: allTags = [] } = useTags();

  // Convert tag IDs to Tag objects for TagPicker
  const selectedTagsForFilter = useMemo(() => {
    const tagMap = new Map(allTags.map((t) => [t.id, t]));
    return tagFilters.map((id) => tagMap.get(id)).filter((t): t is TagRead => t !== undefined);
  }, [allTags, tagFilters]);

  const handleTagFiltersChange = (newTags: TagSummary[]) => {
    setTagFilters(newTags.map((t) => t.id));
  };

  const projectsQuery = useProjects();

  const initiativesQuery = useInitiatives({
    enabled: user?.role === "admin" || hasClaimedManagerRole,
  });
  // Filter initiatives where user can create projects
  const creatableInitiatives = useMemo(() => {
    if (!initiativesQuery.data || !user) {
      return [];
    }
    return initiativesQuery.data.filter((initiative) =>
      initiative.members?.some((member) => member.user.id === user.id && member.can_create_projects)
    );
  }, [initiativesQuery.data, user]);
  const isProjectManager = creatableInitiatives.length > 0;

  // Check if user can view projects for the filtered initiative
  const canViewProjects = useMemo(() => {
    // If no specific initiative is filtered, user can view the page
    const effectiveInitiativeId = lockedInitiativeId ?? filteredInitiativeId;
    if (!effectiveInitiativeId || !user) {
      return true;
    }
    const initiative = initiativesQuery.data?.find((i) => i.id === effectiveInitiativeId);
    if (!initiative) {
      return true; // Initiative not loaded yet, assume access
    }
    const membership = initiative.members?.find((m) => m.user.id === user.id);
    if (!membership) {
      return true; // Not a member, let the backend handle access control
    }
    return membership.can_view_projects !== false;
  }, [lockedInitiativeId, filteredInitiativeId, user, initiativesQuery.data]);

  // Use explicit canCreate prop if provided (from role permissions), otherwise check filtered initiative permissions
  const canCreateProjects = useMemo(() => {
    // If explicit prop provided (e.g., from InitiativeDetailPage), use it
    if (canCreate !== undefined) {
      return canCreate;
    }
    // If a specific initiative is filtered, check permissions for that initiative
    if (filteredInitiativeId && filteredInitiativePermissions) {
      return canCreatePermission(filteredInitiativePermissions, "projects");
    }
    // Fall back to legacy check (user is PM in any initiative)
    return isProjectManager;
  }, [canCreate, filteredInitiativeId, filteredInitiativePermissions, isProjectManager]);

  // Helper function for per-project DAC checks
  const hasProjectWritePermission = (project: ProjectRead): boolean => {
    if (!user) return false;
    const permission = project.permissions?.find((p) => p.user_id === user.id);
    return permission?.level === "owner" || permission?.level === "write";
  };

  const templatesQuery = useTemplateProjects();
  const archivedQuery = useArchivedProjects();

  useEffect(() => {
    if (!canCreateProjects) {
      setIsComposerOpen(false);
      setInitiativeId(null);
      return;
    }
    // Don't override if we're opening from URL params
    const urlInitiativeId = searchParams.initiativeId;
    if (initiativeId || urlInitiativeId) {
      return;
    }
    if (creatableInitiatives.length > 0) {
      setInitiativeId(String(creatableInitiatives[0].id));
    }
  }, [canCreateProjects, initiativeId, creatableInitiatives, searchParams]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const mediaQuery = window.matchMedia("(min-width: 640px)");
    const handleChange = (event: MediaQueryListEvent) => {
      setFiltersOpen(event.matches);
    };
    setFiltersOpen(mediaQuery.matches);
    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", handleChange);
      return () => mediaQuery.removeEventListener("change", handleChange);
    }
    mediaQuery.addListener(handleChange);
    return () => mediaQuery.removeListener(handleChange);
  }, []);

  const reorderProjects = useReorderProjects();

  useEffect(() => {
    setItem(PROJECT_SEARCH_KEY, searchQuery);
  }, [searchQuery]);

  useEffect(() => {
    setItem(PROJECT_SORT_KEY, sortMode);
  }, [sortMode]);

  useEffect(() => {
    setItem(PROJECT_VIEW_KEY, viewMode);
  }, [viewMode]);

  useEffect(() => {
    if (fixedTagIds) return;
    setItem(PROJECT_TAG_FILTERS_KEY, JSON.stringify(tagFilters));
  }, [tagFilters, fixedTagIds]);

  useEffect(() => {
    const projects = projectsQuery.data?.items ?? [];
    const reorderableProjects = projects.filter((project) => !project.pinned_at);
    if (reorderableProjects.length === 0) {
      setCustomOrder((prev) => (prev.length ? [] : prev));
      return;
    }
    const projectIds = reorderableProjects.map((project) => project.id);
    setCustomOrder((prev) => {
      if (
        prev.length === projectIds.length &&
        prev.every((id, index) => id === projectIds[index])
      ) {
        return prev;
      }
      return projectIds;
    });
  }, [projectsQuery.data]);

  const handleComposerOpenChange = (open: boolean) => {
    setIsComposerOpen(open);
    if (!open) {
      if (searchParams.create) {
        isClosingComposer.current = true;
        router.navigate({
          to: "/projects",
          search: { initiativeId: searchParams.initiativeId },
          replace: true,
        });
      }
    }
  };

  const projects = useMemo(() => projectsQuery.data?.items ?? [], [projectsQuery.data]);

  const availableInitiatives = useMemo(() => {
    const initiatives = Array.isArray(initiativesQuery.data) ? initiativesQuery.data : [];
    return initiatives.sort((a, b) => a.name.localeCompare(b.name));
  }, [initiativesQuery.data]);

  // Filter initiatives where user can view projects (for the dropdown)
  const viewableInitiatives = useMemo(() => {
    if (!user) return availableInitiatives;
    return availableInitiatives.filter((initiative) => {
      const membership = initiative.members?.find((m) => m.user.id === user.id);
      // If not a member, include it (backend will handle access control)
      if (!membership) return true;
      return membership.can_view_projects !== false;
    });
  }, [availableInitiatives, user]);

  const lockedInitiative = lockedInitiativeId
    ? (availableInitiatives.find((init) => init.id === lockedInitiativeId) ?? null)
    : null;

  // Get IDs of initiatives where user can view projects
  const viewableInitiativeIds = useMemo(() => {
    return new Set(viewableInitiatives.map((i) => i.id));
  }, [viewableInitiatives]);

  const filteredProjects = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    const tagFilterSet = new Set(tagFilters);
    return projects.filter((project) => {
      const projectInitiativeId = project.initiative?.id ?? project.initiative_id ?? null;
      // Filter by viewable initiatives (role permissions)
      if (user && projectInitiativeId !== null && !viewableInitiativeIds.has(projectInitiativeId)) {
        return false;
      }
      const matchesSearch = !query ? true : project.name.toLowerCase().includes(query);
      const matchesInitiative =
        initiativeFilter === INITIATIVE_FILTER_ALL ||
        (projectInitiativeId !== null &&
          projectInitiativeId !== undefined &&
          initiativeFilter === projectInitiativeId.toString());
      const matchesFavorites = !favoritesOnly ? true : Boolean(project.is_favorited);
      const matchesTags =
        tagFilterSet.size === 0 || (project.tags?.some((tag) => tagFilterSet.has(tag.id)) ?? false);
      return matchesSearch && matchesInitiative && matchesFavorites && matchesTags;
    });
  }, [
    projects,
    searchQuery,
    initiativeFilter,
    favoritesOnly,
    tagFilters,
    user,
    viewableInitiativeIds,
  ]);

  const pinnedProjects = useMemo(() => {
    return filteredProjects
      .filter((project) => Boolean(project.pinned_at))
      .sort((a, b) => {
        const aPinned = a.pinned_at ? new Date(a.pinned_at).getTime() : 0;
        const bPinned = b.pinned_at ? new Date(b.pinned_at).getTime() : 0;
        if (aPinned === bPinned) {
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
        }
        return bPinned - aPinned;
      });
  }, [filteredProjects]);

  const unpinnedProjects = useMemo(
    () => filteredProjects.filter((project) => !project.pinned_at),
    [filteredProjects]
  );

  const sortedProjects = useMemo(() => {
    const next = [...unpinnedProjects];
    if (sortMode === "alphabetical") {
      next.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortMode === "created") {
      next.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    } else if (sortMode === "updated") {
      next.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
    } else if (sortMode === "recently_viewed") {
      next.sort((a, b) => {
        const aViewed = a.last_viewed_at ? new Date(a.last_viewed_at).getTime() : 0;
        const bViewed = b.last_viewed_at ? new Date(b.last_viewed_at).getTime() : 0;
        if (aViewed === bViewed) {
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
        }
        return bViewed - aViewed;
      });
    } else {
      const orderMap = new Map<number, number>();
      customOrder.forEach((id, index) => orderMap.set(id, index));
      next.sort((a, b) => {
        const aIndex = orderMap.has(a.id) ? orderMap.get(a.id)! : Number.MAX_SAFE_INTEGER;
        const bIndex = orderMap.has(b.id) ? orderMap.get(b.id)! : Number.MAX_SAFE_INTEGER;
        return aIndex - bIndex;
      });
    }
    return next;
  }, [unpinnedProjects, sortMode, customOrder]);

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, {
      activationConstraint: {
        delay: 200,
        tolerance: 8,
      },
    })
  ); // Touch drags use a short press to keep scrolling intuitive.

  const handleProjectDragEnd = (event: DragEndEvent) => {
    if (sortMode !== "custom") {
      return;
    }
    const { active, over } = event;
    if (!over || active.id === over.id) {
      return;
    }
    setCustomOrder((prev) => {
      const activeId = Number(active.id);
      const overId = Number(over.id);
      const oldIndex = prev.indexOf(activeId);
      const newIndex = prev.indexOf(overId);
      if (oldIndex === -1 || newIndex === -1) {
        return prev;
      }
      const nextOrder = arrayMove(prev, oldIndex, newIndex);
      reorderProjects.mutate(nextOrder);
      return nextOrder;
    });
  };

  const projectCards =
    sortMode === "custom" ? (
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleProjectDragEnd}
      >
        <SortableContext
          items={sortedProjects.map((project) => project.id.toString())}
          strategy={verticalListSortingStrategy}
        >
          {viewMode === "list" ? (
            <div className="space-y-3">
              {sortedProjects.map((project) => (
                <SortableProjectRowLink key={project.id} project={project} userId={user?.id} />
              ))}
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {sortedProjects.map((project) => (
                <SortableProjectCardLink key={project.id} project={project} userId={user?.id} />
              ))}
            </div>
          )}
        </SortableContext>
      </DndContext>
    ) : (
      <>
        {viewMode === "list" ? (
          <div className="space-y-3">
            {sortedProjects.map((project) => (
              <ProjectRowLink key={project.id} project={project} userId={user?.id} />
            ))}
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {sortedProjects.map((project) => (
              <ProjectCardLink key={project.id} project={project} userId={user?.id} />
            ))}
          </div>
        )}
      </>
    );

  const pinnedProjectsSection =
    pinnedProjects.length > 0 ? (
      <div className="border-b pb-4">
        <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
          <PinIcon className="h-4 w-4" />
          {t("pinned")}
        </div>

        {viewMode === "list" ? (
          <div className="space-y-3">
            {pinnedProjects.map((project) => (
              <ProjectRowLink key={`pinned-${project.id}`} project={project} userId={user?.id} />
            ))}
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {pinnedProjects.map((project) => (
              <ProjectCardLink key={`pinned-${project.id}`} project={project} userId={user?.id} />
            ))}
          </div>
        )}
      </div>
    ) : null;

  if (projectsQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("loading")}</p>;
  }

  if (projectsQuery.isError) {
    return <p className="text-destructive text-sm">{t("loadError")}</p>;
  }

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        {!lockedInitiativeId && !fixedTagIds && (
          <div>
            <div className="flex items-baseline gap-4">
              <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
              {canCreateProjects && (
                <Button size="sm" variant="outline" onClick={() => setIsComposerOpen(true)}>
                  <Plus className="h-4 w-4" />
                  {t("addProject")}
                </Button>
              )}
            </div>
            <p className="text-muted-foreground">{t("subtitle")}</p>
          </div>
        )}

        <Tabs
          value={tabValue}
          onValueChange={(value) => setTabValue(value as "active" | "templates" | "archive")}
          className="space-y-6"
        >
          {!fixedTagIds && (
            <TabsList className="w-full justify-start overflow-x-auto">
              <TabsTrigger value="active" className="inline-flex items-center gap-2">
                <LayoutGrid className="h-4 w-4" />
                {t("tabs.active")}
              </TabsTrigger>
              <TabsTrigger value="templates" className="inline-flex items-center gap-2">
                <ScrollText className="h-4 w-4" />
                {t("tabs.templates")}
              </TabsTrigger>
              <TabsTrigger value="archive" className="inline-flex items-center gap-2">
                <Archive className="h-4 w-4" />
                {t("tabs.archive")}
              </TabsTrigger>
            </TabsList>
          )}

          <TabsContent value="active" className="space-y-4">
            <div className="flex flex-wrap items-center justify-end gap-3">
              {canCreateProjects && lockedInitiativeId && (
                <Button variant="outline" onClick={() => setIsComposerOpen(true)}>
                  <Plus className="h-4 w-4" />
                  {t("addProject")}
                </Button>
              )}
              <Tabs
                value={viewMode}
                onValueChange={(value) => setViewMode(value as "grid" | "list")}
                className="w-auto"
              >
                <TabsList className="grid grid-cols-2">
                  <TabsTrigger value="grid" className="inline-flex items-center gap-2">
                    <LayoutGrid className="h-4 w-4" />
                    {t("view.grid")}
                  </TabsTrigger>
                  <TabsTrigger value="list" className="inline-flex items-center gap-2">
                    <List className="h-4 w-4" />
                    {t("view.list")}
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
            <ProjectsFilterBar
              searchQuery={searchQuery}
              onSearchQueryChange={setSearchQuery}
              initiativeFilter={initiativeFilter}
              onInitiativeFilterChange={setInitiativeFilter}
              lockedInitiativeId={lockedInitiativeId}
              lockedInitiativeName={lockedInitiative?.name ?? null}
              viewableInitiatives={viewableInitiatives}
              filtersOpen={filtersOpen}
              onFiltersOpenChange={setFiltersOpen}
              sortMode={sortMode}
              onSortModeChange={setSortMode}
              favoritesOnly={favoritesOnly}
              onFavoritesOnlyChange={setFavoritesOnly}
              tagFilters={selectedTagsForFilter}
              onTagFiltersChange={handleTagFiltersChange}
              fixedTagIds={fixedTagIds}
            />

            {!canViewProjects ? (
              <Card className="border-destructive/50 bg-destructive/5">
                <CardHeader>
                  <CardTitle className="text-destructive">{t("accessRestricted")}</CardTitle>
                  <CardDescription>{t("accessRestrictedDescription")}</CardDescription>
                </CardHeader>
              </Card>
            ) : filteredProjects.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                {projects.length === 0 ? t("noProjects") : t("noMatchingProjects")}
              </p>
            ) : (
              <>
                {pinnedProjectsSection}
                {sortedProjects.length > 0 ? (
                  projectCards
                ) : pinnedProjects.length > 0 ? (
                  <p className="text-muted-foreground text-sm">{t("onlyPinnedMatch")}</p>
                ) : null}
              </>
            )}
          </TabsContent>

          <TabsContent value="templates">
            {!canViewProjects ? (
              <Card className="border-destructive/50 bg-destructive/5">
                <CardHeader>
                  <CardTitle className="text-destructive">{t("accessRestricted")}</CardTitle>
                  <CardDescription>{t("accessRestrictedDescription")}</CardDescription>
                </CardHeader>
              </Card>
            ) : templatesQuery.isLoading ? (
              <p className="text-muted-foreground text-sm">{t("templates.loading")}</p>
            ) : templatesQuery.isError ? (
              <p className="text-destructive text-sm">{t("templates.loadError")}</p>
            ) : templatesQuery.data?.items?.length ? (
              <div className="grid gap-4 md:grid-cols-2">
                {templatesQuery.data.items.map((template) => (
                  <Card key={template.id} className="shadow-sm">
                    <CardHeader>
                      <CardTitle className="text-xl">{template.name}</CardTitle>
                      {template.description ? (
                        <Markdown content={template.description} className="text-sm" />
                      ) : null}
                    </CardHeader>
                    <CardContent className="text-muted-foreground space-y-2 text-sm">
                      {template.initiative ? (
                        <p>{t("templates.initiativeLabel", { name: template.initiative.name })}</p>
                      ) : null}
                      <p>
                        {t("templates.lastUpdated", {
                          date: new Date(template.updated_at).toLocaleString(),
                        })}
                      </p>
                    </CardContent>
                    <CardFooter className="flex flex-wrap gap-3">
                      <Button asChild variant="link" className="px-0">
                        <Link to={gp(`/projects/${template.id}`)}>
                          {t("templates.viewTemplate")}
                        </Link>
                      </Button>
                      {hasProjectWritePermission(template) ? (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => removeTemplate.mutate(template.id)}
                          disabled={removeTemplate.isPending}
                        >
                          {t("templates.stopUsingAsTemplate")}
                        </Button>
                      ) : null}
                    </CardFooter>
                  </Card>
                ))}
              </div>
            ) : (
              <Card className="shadow-sm">
                <CardHeader>
                  <CardTitle>{t("templates.noTemplates")}</CardTitle>
                  <CardDescription>{t("templates.noTemplatesDescription")}</CardDescription>
                </CardHeader>
              </Card>
            )}
          </TabsContent>

          <TabsContent value="archive">
            {!canViewProjects ? (
              <Card className="border-destructive/50 bg-destructive/5">
                <CardHeader>
                  <CardTitle className="text-destructive">{t("accessRestricted")}</CardTitle>
                  <CardDescription>{t("accessRestrictedDescription")}</CardDescription>
                </CardHeader>
              </Card>
            ) : archivedQuery.isLoading ? (
              <p className="text-muted-foreground text-sm">{t("archived.loading")}</p>
            ) : archivedQuery.isError ? (
              <p className="text-destructive text-sm">{t("archived.loadError")}</p>
            ) : archivedQuery.data?.items?.length ? (
              <div className="grid gap-4 md:grid-cols-2">
                {archivedQuery.data.items.map((archived) => (
                  <Card key={archived.id} className="shadow-sm">
                    <CardHeader>
                      <CardTitle className="text-xl">{archived.name}</CardTitle>
                      {archived.description ? (
                        <Markdown content={archived.description} className="text-sm" />
                      ) : null}
                    </CardHeader>
                    <CardContent className="text-muted-foreground space-y-2 text-sm">
                      {archived.initiative ? (
                        <p>{t("archived.initiativeLabel", { name: archived.initiative.name })}</p>
                      ) : null}
                      <p>
                        {t("archived.archivedAt", {
                          date: archived.archived_at
                            ? new Date(archived.archived_at).toLocaleString()
                            : t("archived.archivedAtUnknown"),
                        })}
                      </p>
                    </CardContent>
                    <CardFooter className="flex flex-wrap gap-3">
                      <Button asChild variant="link" className="px-0">
                        <Link to={gp(`/projects/${archived.id}`)}>{t("archived.viewDetails")}</Link>
                      </Button>
                      {hasProjectWritePermission(archived) ? (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => unarchiveProject.mutate(archived.id)}
                          disabled={unarchiveProject.isPending}
                        >
                          {t("archived.unarchive")}
                        </Button>
                      ) : null}
                    </CardFooter>
                  </Card>
                ))}
              </div>
            ) : (
              <Card className="shadow-sm">
                <CardHeader>
                  <CardTitle>{t("archived.noArchived")}</CardTitle>
                  <CardDescription>{t("archived.noArchivedDescription")}</CardDescription>
                </CardHeader>
              </Card>
            )}
          </TabsContent>
        </Tabs>

        {canCreateProjects && (
          <Button
            className="shadow-primary/40 fixed right-6 bottom-6 z-40 h-12 rounded-full px-6 shadow-lg"
            onClick={() => setIsComposerOpen(true)}
          >
            <Plus className="h-4 w-4" />
            {t("addProject")}
          </Button>
        )}

        {canCreateProjects && (
          <CreateProjectDialog
            open={isComposerOpen}
            onOpenChange={handleComposerOpenChange}
            lockedInitiativeId={lockedInitiativeId}
            lockedInitiativeName={lockedInitiative?.name ?? null}
            creatableInitiatives={creatableInitiatives}
            initiativesQuery={{
              isLoading: initiativesQuery.isLoading,
              isError: initiativesQuery.isError,
            }}
            defaultInitiativeId={initiativeId}
            onCreated={() => handleComposerOpenChange(false)}
          />
        )}
      </div>
    </PullToRefresh>
  );
};

export const ProjectsPage = () => <ProjectsView />;

const SortableProjectCardLink = ({
  project,
  userId,
}: {
  project: ProjectRead;
  userId?: number;
}) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: project.id.toString(),
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };
  const dragHandleProps: HTMLAttributes<HTMLButtonElement> = {
    ...attributes,
    ...listeners,
    onClick: (event) => {
      event.preventDefault();
      event.stopPropagation();
    },
  };
  return (
    <div ref={setNodeRef} style={style} className={isDragging ? "opacity-70" : undefined}>
      <ProjectCardLink project={project} dragHandleProps={dragHandleProps} userId={userId} />
    </div>
  );
};

const SortableProjectRowLink = ({ project, userId }: { project: ProjectRead; userId?: number }) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: project.id.toString(),
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };
  const dragHandleProps: HTMLAttributes<HTMLButtonElement> = {
    ...attributes,
    ...listeners,
    onClick: (event) => {
      event.preventDefault();
      event.stopPropagation();
    },
  };
  return (
    <div ref={setNodeRef} style={style} className={isDragging ? "opacity-70" : undefined}>
      <ProjectRowLink project={project} dragHandleProps={dragHandleProps} userId={userId} />
    </div>
  );
};
