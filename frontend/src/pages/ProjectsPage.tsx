import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Link } from "@tanstack/react-router";
import {
  Archive,
  FileDown,
  LayoutGrid,
  List,
  Pin as PinIcon,
  Plus,
  ScrollText,
} from "lucide-react";
import { type HTMLAttributes, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectRead, TagRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllProjects } from "@/api/query-keys";
import { BulkAccessBar, canManageSharing } from "@/components/access/BulkAccessBar";
import { BulkEditAccessDialog } from "@/components/access/BulkEditAccessDialog";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { BulkExportButton } from "@/components/exports/BulkExportButton";
import { ToolImportAction } from "@/components/imports/ToolImportAction";
import { Markdown } from "@/components/Markdown";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { PullToRefresh } from "@/components/PullToRefresh";
import { CreateProjectDialog } from "@/components/projects/CreateProjectDialog";
import { ProjectCardLink, ProjectRowLink } from "@/components/projects/ProjectPreview";
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
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useDefaultFiltersOpen } from "@/hooks/useDefaultFiltersOpen";
import { useGridSelection } from "@/hooks/useGridSelection";
import { useInitiativeAccess, useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import {
  useArchivedProjects,
  useProjects,
  useRemoveProjectTemplate,
  useReorderProjects,
  useTemplateProjects,
  useUnarchiveProject,
} from "@/hooks/useProjects";
import { useTags } from "@/hooks/useTags";
import { useViewPreference } from "@/hooks/useViewPreference";
import { useGuildPath } from "@/lib/guildUrl";
import { hasWriteAccess } from "@/lib/permissions";
import { toolDetailRoute } from "@/lib/tools";

const PROJECT_SORT_KEY = "project:list:sort";
const PROJECT_SEARCH_KEY = "project:list:search";
const PROJECT_VIEW_KEY = "project:list:view-mode";
const PROJECT_TAG_FILTERS_KEY = "project:list:tag-filters";

/**
 * Scoped one of two ways, never both and never neither: to an initiative (the
 * initiative page's Projects tab) or to a tag (the cross-initiative tag
 * browse). Stating it as a union keeps "unscoped is only legal for the tag
 * browse" a fact the compiler checks rather than a comment that rots.
 */
type ProjectsViewProps =
  | { fixedInitiativeId: number; fixedTagIds?: never; canCreate?: boolean }
  | { fixedInitiativeId?: never; fixedTagIds: number[]; canCreate?: boolean };

export const ProjectsView = ({ fixedInitiativeId, fixedTagIds, canCreate }: ProjectsViewProps) => {
  const { t } = useTranslation(["projects", "common", "access"]);
  const { user } = useAuth();
  // Single source of truth for "what can I do in each initiative" — honors
  // guild-admin / PAM / membership so this page never re-derives access from
  // raw membership flags (which would wrongly exclude guild admins).
  const { isGuildAdmin, isGrantGuild } = useInitiativeAccess();
  const gp = useGuildPath();
  const lockedInitiativeId = typeof fixedInitiativeId === "number" ? fixedInitiativeId : null;

  const handleRefresh = useCallback(async () => {
    await invalidateAllProjects();
  }, []);
  const {
    open: isComposerOpen,
    setOpen: setIsComposerOpen,
    onOpenChange: handleComposerOpenChange,
  } = useCreateFromSearchParam();
  const [searchQuery, setSearchQuery] = useViewPreference<string>(PROJECT_SEARCH_KEY, "");
  type ProjectSortMode = "custom" | "updated" | "created" | "alphabetical" | "recently_viewed";
  const [persistedSortMode, setPersistedSortMode] = useViewPreference<ProjectSortMode>(
    PROJECT_SORT_KEY,
    "custom"
  );
  const sortMode: ProjectSortMode =
    persistedSortMode === "custom" ||
    persistedSortMode === "updated" ||
    persistedSortMode === "created" ||
    persistedSortMode === "alphabetical" ||
    persistedSortMode === "recently_viewed"
      ? persistedSortMode
      : "custom";
  const setSortMode = useCallback(
    (next: ProjectSortMode) => setPersistedSortMode(next),
    [setPersistedSortMode]
  );
  const [customOrder, setCustomOrder] = useState<number[]>([]);
  const removeTemplate = useRemoveProjectTemplate();

  const [favoritesOnly, setFavoritesOnly] = useState(false);

  const unarchiveProject = useUnarchiveProject();

  const [persistedViewMode, setPersistedViewMode] = useViewPreference<string>(
    PROJECT_VIEW_KEY,
    "grid"
  );
  const viewMode: "grid" | "list" =
    persistedViewMode === "list" || persistedViewMode === "grid" ? persistedViewMode : "grid";
  const setViewMode = useCallback(
    (next: "grid" | "list") => setPersistedViewMode(next),
    [setPersistedViewMode]
  );
  const [tabValue, setTabValue] = useState<"active" | "templates" | "archive">("active");
  const [filtersOpen, setFiltersOpen] = useDefaultFiltersOpen();

  const [persistedTagFilters, setPersistedTagFilters] = useViewPreference<number[]>(
    PROJECT_TAG_FILTERS_KEY,
    []
  );
  const tagFilters = fixedTagIds
    ? fixedTagIds
    : Array.isArray(persistedTagFilters)
      ? persistedTagFilters.filter((n): n is number => typeof n === "number" && Number.isFinite(n))
      : [];
  const setTagFilters = useCallback(
    (next: number[] | ((prev: number[]) => number[])) => {
      if (fixedTagIds) return;
      setPersistedTagFilters((prev) => {
        const safe = Array.isArray(prev) ? prev : [];
        return typeof next === "function" ? next(safe) : next;
      });
    },
    [fixedTagIds, setPersistedTagFilters]
  );

  const { data: allTags = [] } = useTags();

  // Convert tag IDs to Tag objects for TagPicker
  const selectedTagsForFilter = useMemo(() => {
    const tagMap = new Map(allTags.map((t) => [t.id, t]));
    return tagFilters.map((id) => tagMap.get(id)).filter((t): t is TagRead => t !== undefined);
  }, [allTags, tagFilters]);

  const handleTagFiltersChange = (newTags: TagSummary[]) => {
    setTagFilters(newTags.map((t) => t.id));
  };

  // Scoped in SQL rather than filtered here: the tab only ever shows one
  // initiative's projects, and the tag browse spans them all.
  const projectsQuery = useProjects(
    lockedInitiativeId ? { initiative_id: lockedInitiativeId } : undefined
  );

  // This is a guild-scoped page and the initiatives list is cheap + cached, so
  // fetch it unconditionally. Create access is derived from the same payload
  // by useToolCreateAccess, which already honors guild-admin / PAM grants — no
  // need to pre-gate on a claimed manager role from user.initiative_roles (the
  // /users/me object no longer populates that field: initiative membership is
  // guild-schema content).
  const initiativesQuery = useInitiatives();
  // Canonical create answer: the locked/filtered initiative's server-computed
  // create flag, or (in the "All" view) whether any visible initiative grants
  // it. `creatableInitiatives` feeds the create dialog's initiative picker.
  const { canCreate: canCreateDerived, creatableInitiatives } = useToolCreateAccess(Tool.project, {
    initiativeId: lockedInitiativeId,
  });

  // Check if user can view projects for the filtered initiative
  const canViewProjects = useMemo(() => {
    // Guild admins / PAM grantees always have access — a membership row must
    // never downgrade them.
    if (isGuildAdmin || isGrantGuild) {
      return true;
    }
    // The cross-initiative tag browse has no one initiative to check.
    const effectiveInitiativeId = lockedInitiativeId;
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
  }, [lockedInitiativeId, user, initiativesQuery.data, isGuildAdmin, isGrantGuild]);

  // An explicit canCreate prop (e.g. from InitiativeDetailPage) wins; otherwise
  // use the canonical derivation above.
  const canCreateProjects = canCreate ?? canCreateDerived;

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canCreateProjects ? { run: () => setIsComposerOpen(true), label: t("addProject") } : null
  );

  // Helper function for per-project DAC checks
  const hasProjectWritePermission = (project: ProjectRead): boolean => {
    if (!user) return false;
    return hasWriteAccess(project.my_permission_level);
  };

  const templatesQuery = useTemplateProjects(lockedInitiativeId);
  const archivedQuery = useArchivedProjects(lockedInitiativeId);

  useEffect(() => {
    if (!canCreateProjects) {
      setIsComposerOpen(false);
    }
  }, [canCreateProjects, setIsComposerOpen]);

  const reorderProjects = useReorderProjects();

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

  const lockedInitiativeName = lockedInitiativeId
    ? (availableInitiatives.find((init) => init.id === lockedInitiativeId)?.name ?? null)
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
      const matchesFavorites = !favoritesOnly ? true : Boolean(project.is_favorited);
      const matchesTags =
        tagFilterSet.size === 0 || (project.tags?.some((tag) => tagFilterSet.has(tag.id)) ?? false);
      return matchesSearch && matchesFavorites && matchesTags;
    });
  }, [projects, searchQuery, favoritesOnly, tagFilters, user, viewableInitiativeIds]);

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
      customOrder.forEach((id, index) => {
        orderMap.set(id, index);
      });
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

  const selection = useGridSelection<(typeof sortedProjects)[number]>();
  const [bulkAccessOpen, setBulkAccessOpen] = useState(false);

  const projectCards = selection.active ? (
    viewMode === "list" ? (
      <div className="space-y-3">
        {sortedProjects.map((project) => (
          <SelectableGridItem
            key={project.id}
            active
            selected={selection.selectedIds.has(project.id)}
            onToggle={() => selection.toggle(project)}
            label={project.name}
          >
            <ProjectRowLink project={project} userId={user?.id} />
          </SelectableGridItem>
        ))}
      </div>
    ) : (
      <div className="grid gap-4 md:grid-cols-2">
        {sortedProjects.map((project) => (
          <SelectableGridItem
            key={project.id}
            active
            selected={selection.selectedIds.has(project.id)}
            onToggle={() => selection.toggle(project)}
            label={project.name}
          >
            <ProjectCardLink project={project} userId={user?.id} />
          </SelectableGridItem>
        ))}
      </div>
    )
  ) : sortMode === "custom" ? (
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
        <div className="inline-flex items-center gap-2 font-medium text-muted-foreground text-sm">
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
              <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
              {canCreateProjects && (
                <Button size="sm" variant="outline" onClick={() => setIsComposerOpen(true)}>
                  <Plus className="h-4 w-4" />
                  {t("addProject")}
                </Button>
              )}
              <ToolImportAction tool={Tool.project} canImport={canCreateProjects} />
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
              {lockedInitiativeId && (
                <ToolImportAction
                  tool={Tool.project}
                  canImport={canCreateProjects}
                  fixedInitiativeId={lockedInitiativeId}
                />
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
              {canViewProjects && sortedProjects.length > 0 && !selection.active && (
                <Button variant="outline" onClick={selection.enter}>
                  {t("access:bulkBar.select")}
                </Button>
              )}
            </div>
            <ProjectsFilterBar
              searchQuery={searchQuery}
              onSearchQueryChange={setSearchQuery}
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
              <div className="space-y-3">
                <p className="text-muted-foreground text-sm">
                  {projects.length === 0 ? t("noProjects") : t("noMatchingProjects")}
                </p>
                {projects.length === 0 && (
                  <ToolImportAction
                    tool={Tool.project}
                    canImport={canCreateProjects}
                    fixedInitiativeId={lockedInitiativeId ?? undefined}
                    variant="button"
                  />
                )}
              </div>
            ) : (
              <>
                {selection.active ? (
                  <BulkAccessBar
                    count={selection.selectedItems.length}
                    canManage={canManageSharing(selection.selectedItems)}
                    onEditAccess={() => setBulkAccessOpen(true)}
                    onExit={selection.exit}
                  >
                    {selection.selectedItems.length > 0 &&
                      // Project backups require WRITE on every selected
                      // project (the backend refuses mixed selections).
                      (canManageSharing(selection.selectedItems) ? (
                        <BulkExportButton
                          tool={Tool.project}
                          ids={selection.selectedItems.map((p) => p.id)}
                        />
                      ) : (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled
                          title={t("export.noWriteAccess")}
                        >
                          <FileDown className="h-4 w-4" />
                          <span className="hidden sm:ml-2 sm:inline">
                            {t("export.exportButton")}
                          </span>
                        </Button>
                      ))}
                  </BulkAccessBar>
                ) : (
                  pinnedProjectsSection
                )}
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
                    <CardContent className="space-y-2 text-muted-foreground text-sm">
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
                        <Link
                          to={gp(
                            toolDetailRoute(Tool.project, template.initiative_id, template.id)
                          )}
                        >
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
                    <CardContent className="space-y-2 text-muted-foreground text-sm">
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
                        <Link
                          to={gp(
                            toolDetailRoute(Tool.project, archived.initiative_id, archived.id)
                          )}
                        >
                          {t("archived.viewDetails")}
                        </Link>
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
          <CreateProjectDialog
            open={isComposerOpen}
            onOpenChange={handleComposerOpenChange}
            lockedInitiativeId={lockedInitiativeId}
            lockedInitiativeName={lockedInitiativeName}
            creatableInitiatives={creatableInitiatives}
            initiativesQuery={{
              isLoading: initiativesQuery.isLoading,
              isError: initiativesQuery.isError,
            }}
            defaultInitiativeId={lockedInitiativeId ? String(lockedInitiativeId) : null}
            onCreated={() => handleComposerOpenChange(false)}
          />
        )}

        <BulkEditAccessDialog
          open={bulkAccessOpen}
          onOpenChange={setBulkAccessOpen}
          items={selection.selectedItems}
          resourceType={Tool.project}
          invalidate={invalidateAllProjects}
          onSuccess={selection.exit}
        />
      </div>
    </PullToRefresh>
  );
};

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
