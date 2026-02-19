import {
  FormEvent,
  HTMLAttributes,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
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
import {
  LayoutGrid,
  ScrollText,
  Archive,
  List,
  Filter,
  ChevronDown,
  Plus,
  Pin as PinIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  listProjectsApiV1ProjectsGet,
  getListProjectsApiV1ProjectsGetQueryKey,
  createProjectApiV1ProjectsPost,
  updateProjectApiV1ProjectsProjectIdPatch,
  unarchiveProjectApiV1ProjectsProjectIdUnarchivePost,
  reorderProjectsApiV1ProjectsReorderPost,
} from "@/api/generated/projects/projects";
import {
  listInitiativesApiV1InitiativesGet,
  getListInitiativesApiV1InitiativesGetQueryKey,
} from "@/api/generated/initiatives/initiatives";
import { invalidateAllProjects } from "@/api/query-keys";
import { getItem, setItem } from "@/lib/storage";
import { useGuildPath } from "@/lib/guildUrl";
import { Markdown } from "@/components/Markdown";
import { PullToRefresh } from "@/components/PullToRefresh";
import { ProjectCardLink, ProjectRowLink } from "@/components/projects/ProjectPreview";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { EmojiPicker } from "@/components/EmojiPicker";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import {
  useMyInitiativePermissions,
  canCreate as canCreatePermission,
} from "@/hooks/useInitiativeRoles";
import { Project, Initiative } from "@/types/api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { TagPicker } from "@/components/tags/TagPicker";
import { useTags } from "@/hooks/useTags";
import type { Tag, TagSummary } from "@/types/api";

const NO_TEMPLATE_VALUE = "template-none";
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
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [icon, setIcon] = useState("");
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
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>(NO_TEMPLATE_VALUE);
  const [isTemplateProject, setIsTemplateProject] = useState(false);
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
  const removeTemplate = useMutation({
    mutationFn: async (projectId: number) => {
      await updateProjectApiV1ProjectsProjectIdPatch(projectId, { is_template: false });
    },
    onSuccess: () => {
      void invalidateAllProjects();
    },
  });

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

  const unarchiveProject = useMutation({
    mutationFn: async (projectId: number) => {
      await unarchiveProjectApiV1ProjectsProjectIdUnarchivePost(projectId);
    },
    onSuccess: () => {
      void invalidateAllProjects();
    },
  });

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
    return tagFilters.map((id) => tagMap.get(id)).filter((t): t is Tag => t !== undefined);
  }, [allTags, tagFilters]);

  const handleTagFiltersChange = (newTags: TagSummary[]) => {
    setTagFilters(newTags.map((t) => t.id));
  };

  const projectsQuery = useQuery<Project[]>({
    queryKey: getListProjectsApiV1ProjectsGetQueryKey(),
    queryFn: () => listProjectsApiV1ProjectsGet() as unknown as Promise<Project[]>,
  });

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: getListInitiativesApiV1InitiativesGetQueryKey(),
    enabled: user?.role === "admin" || hasClaimedManagerRole,
    queryFn: () => listInitiativesApiV1InitiativesGet() as unknown as Promise<Initiative[]>,
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
  const hasProjectWritePermission = (project: Project): boolean => {
    if (!user) return false;
    const permission = project.permissions?.find((p) => p.user_id === user.id);
    return permission?.level === "owner" || permission?.level === "write";
  };

  const templatesQuery = useQuery<Project[]>({
    queryKey: getListProjectsApiV1ProjectsGetQueryKey({ template: true }),
    queryFn: () =>
      listProjectsApiV1ProjectsGet({ template: true }) as unknown as Promise<Project[]>,
  });
  const archivedQuery = useQuery<Project[]>({
    queryKey: getListProjectsApiV1ProjectsGetQueryKey({ archived: true }),
    queryFn: () =>
      listProjectsApiV1ProjectsGet({ archived: true }) as unknown as Promise<Project[]>,
  });

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

  const reorderProjects = useMutation({
    mutationFn: async (orderedIds: number[]) => {
      await reorderProjectsApiV1ProjectsReorderPost({ project_ids: orderedIds });
    },
    onSettled: () => {
      void invalidateAllProjects();
    },
  });

  const createProject = useMutation({
    mutationFn: async () => {
      const payload: {
        name: string;
        description: string;
        icon?: string;
        initiative_id?: number;
        template_id?: number;
        is_template?: boolean;
      } = { name, description };
      const trimmedIcon = icon.trim();
      if (trimmedIcon) {
        payload.icon = trimmedIcon;
      }
      const selectedInitiativeId = initiativeId ? Number(initiativeId) : undefined;
      if (!selectedInitiativeId || Number.isNaN(selectedInitiativeId)) {
        throw new Error("Select an initiative before creating a project");
      }
      payload.initiative_id = selectedInitiativeId;
      payload.is_template = isTemplateProject;
      if (!isTemplateProject && selectedTemplateId !== NO_TEMPLATE_VALUE) {
        payload.template_id = Number(selectedTemplateId);
      }
      return createProjectApiV1ProjectsPost(
        payload as Parameters<typeof createProjectApiV1ProjectsPost>[0]
      ) as unknown as Promise<Project>;
    },
    onSuccess: () => {
      setName("");
      setDescription("");
      setIcon("");
      setInitiativeId(null);
      setSelectedTemplateId(NO_TEMPLATE_VALUE);
      setIsTemplateProject(false);
      handleComposerOpenChange(false);
      void invalidateAllProjects();
    },
  });

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
    if (isTemplateProject) {
      return;
    }
    if (selectedTemplateId === NO_TEMPLATE_VALUE) {
      return;
    }
    const templateId = Number(selectedTemplateId);
    if (!Number.isFinite(templateId)) {
      return;
    }
    const template = templatesQuery.data?.find((item) => item.id === templateId);
    if (!template) {
      return;
    }
    setDescription(template.description ?? "");
  }, [selectedTemplateId, templatesQuery.data, isTemplateProject]);

  useEffect(() => {
    const projects = Array.isArray(projectsQuery.data) ? projectsQuery.data : [];
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

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    createProject.mutate();
  };

  const handleComposerOpenChange = (open: boolean) => {
    setIsComposerOpen(open);
    // Clear ?create from URL when dialog closes
    if (!open && searchParams.create) {
      isClosingComposer.current = true;
      router.navigate({
        to: "/projects",
        search: { initiativeId: searchParams.initiativeId },
        replace: true,
      });
    }
  };

  const projects = useMemo(() => projectsQuery.data ?? [], [projectsQuery.data]);

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
            <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
              <div className="flex items-center justify-between sm:hidden">
                <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
                  <Filter className="h-4 w-4" />
                  {t("filters.heading")}
                </div>
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="sm" className="h-8 px-3">
                    {filtersOpen ? t("filters.hide") : t("filters.show")}
                    <ChevronDown
                      className={`ml-1 h-4 w-4 transition-transform ${
                        filtersOpen ? "rotate-180" : ""
                      }`}
                    />
                  </Button>
                </CollapsibleTrigger>
              </div>
              <CollapsibleContent forceMount className="data-[state=closed]:hidden">
                <div className="border-muted bg-background/40 mt-2 flex flex-wrap items-end gap-4 rounded-md border p-3 sm:mt-0">
                  <div className="w-full space-y-2 lg:flex-1">
                    <Label
                      htmlFor="project-search"
                      className="text-muted-foreground block text-xs font-medium"
                    >
                      {t("filters.filterByName")}
                    </Label>
                    <Input
                      id="project-search"
                      placeholder={t("filters.searchProjects")}
                      value={searchQuery}
                      onChange={(event) => setSearchQuery(event.target.value)}
                      className="min-w-60"
                    />
                  </div>
                  {lockedInitiativeId ? (
                    <div className="w-full space-y-2 sm:w-60">
                      <Label className="text-muted-foreground block text-xs font-medium">
                        {t("filters.initiative")}
                      </Label>
                      <p className="text-sm font-medium">
                        {lockedInitiative?.name ?? t("filters.selectedInitiative")}
                      </p>
                    </div>
                  ) : (
                    <div className="w-full space-y-2 sm:w-60">
                      <Label
                        htmlFor="project-initiative-filter"
                        className="text-muted-foreground block text-xs font-medium"
                      >
                        {t("filters.filterByInitiative")}
                      </Label>
                      <Select value={initiativeFilter} onValueChange={setInitiativeFilter}>
                        <SelectTrigger id="project-initiative-filter">
                          <SelectValue placeholder={t("filters.allInitiatives")} />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={INITIATIVE_FILTER_ALL}>
                            {t("filters.allInitiatives")}
                          </SelectItem>
                          {viewableInitiatives.map((initiative) => (
                            <SelectItem key={initiative.id} value={initiative.id.toString()}>
                              {initiative.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                  {!fixedTagIds && (
                    <div className="w-full space-y-2 sm:w-48">
                      <Label
                        htmlFor="tag-filter"
                        className="text-muted-foreground block text-xs font-medium"
                      >
                        {t("filters.filterByTag")}
                      </Label>
                      <TagPicker
                        selectedTags={selectedTagsForFilter}
                        onChange={handleTagFiltersChange}
                        placeholder={t("filters.allTags")}
                        variant="filter"
                      />
                    </div>
                  )}
                  <div className="w-full space-y-2 sm:w-60">
                    <Label
                      htmlFor="project-sort"
                      className="text-muted-foreground block text-xs font-medium"
                    >
                      {t("filters.sortProjects")}
                    </Label>
                    <Select
                      value={sortMode}
                      onValueChange={(value) =>
                        setSortMode(
                          value as
                            | "custom"
                            | "updated"
                            | "created"
                            | "alphabetical"
                            | "recently_viewed"
                        )
                      }
                    >
                      <SelectTrigger id="project-sort">
                        <SelectValue placeholder={t("filters.selectSortOrder")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="custom">{t("filters.sortCustom")}</SelectItem>
                        <SelectItem value="recently_viewed">
                          {t("filters.sortRecentlyOpened")}
                        </SelectItem>
                        <SelectItem value="updated">{t("filters.sortRecentlyUpdated")}</SelectItem>
                        <SelectItem value="created">{t("filters.sortRecentlyCreated")}</SelectItem>
                        <SelectItem value="alphabetical">
                          {t("filters.sortAlphabetical")}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="w-full space-y-2 sm:w-60">
                    <Label
                      htmlFor="favorites-only"
                      className="text-muted-foreground block text-xs font-medium"
                    >
                      {t("filters.favorites")}
                    </Label>
                    <div className="bg-background/60 flex h-10 items-center gap-3 rounded-md border px-3">
                      <Switch
                        id="favorites-only"
                        checked={favoritesOnly}
                        onCheckedChange={(checked) => setFavoritesOnly(Boolean(checked))}
                        aria-label={t("filters.showOnlyFavorites")}
                      />
                      <span className="text-muted-foreground text-sm">
                        {t("filters.showOnlyFavorites")}
                      </span>
                    </div>
                  </div>
                </div>
              </CollapsibleContent>
            </Collapsible>

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
            ) : templatesQuery.data?.length ? (
              <div className="grid gap-4 md:grid-cols-2">
                {templatesQuery.data.map((template) => (
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
            ) : archivedQuery.data?.length ? (
              <div className="grid gap-4 md:grid-cols-2">
                {archivedQuery.data.map((archived) => (
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
          <Dialog open={isComposerOpen} onOpenChange={handleComposerOpenChange}>
            <DialogContent className="bg-card max-h-screen overflow-y-auto">
              <DialogHeader>
                <DialogTitle>{t("createDialog.title")}</DialogTitle>
                <DialogDescription>{t("createDialog.description")}</DialogDescription>
              </DialogHeader>
              <form className="w-full max-w-lg" onSubmit={handleSubmit}>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="project-icon">{t("createDialog.iconLabel")}</Label>
                    <EmojiPicker
                      id="project-icon"
                      value={icon || undefined}
                      onChange={(emoji) => setIcon(emoji ?? "")}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="project-name">{t("createDialog.nameLabel")}</Label>
                    <Input
                      id="project-name"
                      placeholder={t("createDialog.namePlaceholder")}
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="project-description">
                      {t("createDialog.descriptionLabel")}
                    </Label>
                    <Textarea
                      id="project-description"
                      placeholder={t("createDialog.descriptionPlaceholder")}
                      rows={3}
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>{t("createDialog.initiativeLabel")}</Label>
                    {lockedInitiativeId ? (
                      <div className="rounded-md border px-3 py-2 text-sm">
                        {lockedInitiative?.name ?? t("filters.selectedInitiative")}
                      </div>
                    ) : initiativesQuery.isLoading ? (
                      <p className="text-muted-foreground text-sm">
                        {t("createDialog.loadingInitiatives")}
                      </p>
                    ) : initiativesQuery.isError ? (
                      <p className="text-destructive text-sm">
                        {t("createDialog.initiativeLoadError")}
                      </p>
                    ) : creatableInitiatives.length > 0 ? (
                      <Select value={initiativeId ?? ""} onValueChange={setInitiativeId}>
                        <SelectTrigger>
                          <SelectValue placeholder={t("createDialog.selectInitiative")} />
                        </SelectTrigger>
                        <SelectContent>
                          {creatableInitiatives.map((initiative) => (
                            <SelectItem key={initiative.id} value={String(initiative.id)}>
                              {initiative.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <p className="text-muted-foreground text-sm">
                        {t("createDialog.noInitiatives")}
                      </p>
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="project-template">{t("createDialog.templateLabel")}</Label>
                    {templatesQuery.isLoading ? (
                      <p className="text-muted-foreground text-sm">
                        {t("createDialog.loadingTemplates")}
                      </p>
                    ) : templatesQuery.isError ? (
                      <p className="text-destructive text-sm">
                        {t("createDialog.templateLoadError")}
                      </p>
                    ) : (
                      <Select
                        value={selectedTemplateId}
                        onValueChange={setSelectedTemplateId}
                        disabled={isTemplateProject}
                      >
                        <SelectTrigger id="project-template">
                          <SelectValue placeholder={t("createDialog.noTemplate")} />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={NO_TEMPLATE_VALUE}>
                            {t("createDialog.noTemplate")}
                          </SelectItem>
                          {templatesQuery.data?.map((template) => (
                            <SelectItem key={template.id} value={String(template.id)}>
                              {template.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                    {isTemplateProject ? (
                      <p className="text-muted-foreground text-xs">
                        {t("createDialog.disableTemplateHint")}
                      </p>
                    ) : null}
                  </div>
                  <div className="bg-muted/20 flex items-center justify-between rounded-lg border p-3">
                    <div>
                      <Label htmlFor="create-as-template" className="text-base">
                        {t("createDialog.saveAsTemplate")}
                      </Label>
                      <p className="text-muted-foreground text-xs">
                        {t("createDialog.saveAsTemplateHint")}
                      </p>
                    </div>
                    <Switch
                      id="create-as-template"
                      checked={isTemplateProject}
                      onCheckedChange={(checked) => {
                        const nextStatus = Boolean(checked);
                        setIsTemplateProject(nextStatus);
                        if (nextStatus) {
                          setSelectedTemplateId(NO_TEMPLATE_VALUE);
                        }
                      }}
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {createProject.isError ? (
                      <p className="text-destructive text-sm">{t("createDialog.createError")}</p>
                    ) : null}
                    <div className="ml-auto flex gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        disabled={createProject.isPending}
                        onClick={() => handleComposerOpenChange(false)}
                      >
                        {t("common:cancel")}
                      </Button>
                      <Button type="submit" disabled={createProject.isPending}>
                        {createProject.isPending
                          ? t("createDialog.creating")
                          : t("createDialog.createProject")}
                      </Button>
                    </div>
                  </div>
                </div>
              </form>
            </DialogContent>
          </Dialog>
        )}
      </div>
    </PullToRefresh>
  );
};

export const ProjectsPage = () => <ProjectsView />;

const SortableProjectCardLink = ({ project, userId }: { project: Project; userId?: number }) => {
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

const SortableProjectRowLink = ({ project, userId }: { project: Project; userId?: number }) => {
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
