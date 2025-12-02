import { FormEvent, HTMLAttributes, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
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
  GripVertical,
  LayoutGrid,
  ScrollText,
  Archive,
  List,
  Filter,
  ChevronDown,
  Plus,
  Pin as PinIcon,
} from "lucide-react";

import { apiClient } from "@/api/client";
import { Markdown } from "@/components/Markdown";
import { FavoriteProjectButton } from "@/components/projects/FavoriteProjectButton";
import { PinProjectButton } from "@/components/projects/PinProjectButton";
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
import { Progress } from "@/components/ui/progress";
import { ProgressCircle } from "@/components/ui/progress-circle";
import { useAuth } from "@/hooks/useAuth";
import { queryClient } from "@/lib/queryClient";
import { InitiativeColorDot, resolveInitiativeColor } from "@/lib/initiativeColors";
import { Project, ProjectReorderPayload, Initiative } from "@/types/api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const NO_TEMPLATE_VALUE = "template-none";
const INITIATIVE_FILTER_ALL = "all";
const PROJECT_SORT_KEY = "project:list:sort";
const PROJECT_SEARCH_KEY = "project:list:search";
const PROJECT_VIEW_KEY = "project:list:view-mode";
const getDefaultFiltersVisibility = () => {
  if (typeof window === "undefined") {
    return true;
  }
  return window.matchMedia("(min-width: 640px)").matches;
};

export const ProjectsPage = () => {
  const { user } = useAuth();
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
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>(NO_TEMPLATE_VALUE);
  const [isTemplateProject, setIsTemplateProject] = useState(false);
  const [searchQuery, setSearchQuery] = useState<string>(() => {
    if (typeof window === "undefined") {
      return "";
    }
    return localStorage.getItem(PROJECT_SEARCH_KEY) ?? "";
  });
  const [sortMode, setSortMode] = useState<
    "custom" | "updated" | "created" | "alphabetical" | "recently_viewed"
  >(() => {
    if (typeof window === "undefined") {
      return "custom";
    }
    const stored = localStorage.getItem(PROJECT_SORT_KEY);
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
      await apiClient.patch(`/projects/${projectId}`, { is_template: false });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const [initiativeFilter, setInitiativeFilter] = useState<string>(INITIATIVE_FILTER_ALL);
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const unarchiveProject = useMutation({
    mutationFn: async (projectId: number) => {
      await apiClient.post(`/projects/${projectId}/unarchive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["projects", "archived"],
      });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const [viewMode, setViewMode] = useState<"grid" | "list">(() => {
    if (typeof window === "undefined") {
      return "grid";
    }
    const stored = localStorage.getItem(PROJECT_VIEW_KEY);
    return stored === "list" || stored === "grid" ? stored : "grid";
  });
  const [tabValue, setTabValue] = useState<"active" | "templates" | "archive">("active");
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);

  const projectsQuery = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/");
      return response.data;
    },
  });

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: ["initiatives"],
    enabled: user?.role === "admin" || hasClaimedManagerRole,
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
  });
  const guildManagedInitiatives = useMemo(() => {
    if (!initiativesQuery.data || !user) {
      return [];
    }
    return initiativesQuery.data.filter((initiative) =>
      initiative.members?.some(
        (member) => member.user.id === user.id && member.role === "project_manager"
      )
    );
  }, [initiativesQuery.data, user]);
  const isProjectManager = guildManagedInitiatives.length > 0;
  const canManageProjects = user?.role === "admin" || isProjectManager;
  const canPinProjects = user?.role === "admin" || isProjectManager;

  const templatesQuery = useQuery<Project[]>({
    queryKey: ["projects", "templates"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/", {
        params: { template: true },
      });
      return response.data;
    },
  });
  const archivedQuery = useQuery<Project[]>({
    queryKey: ["projects", "archived"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/", {
        params: { archived: true },
      });
      return response.data;
    },
  });

  useEffect(() => {
    if (!canManageProjects) {
      setIsComposerOpen(false);
      setInitiativeId(null);
      return;
    }
    if (initiativeId) {
      return;
    }
    const data = initiativesQuery.data;
    if (data && data.length > 0) {
      setInitiativeId(String(data[0].id));
    }
  }, [canManageProjects, initiativeId, initiativesQuery.data]);

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
      const payload: ProjectReorderPayload = { project_ids: orderedIds };
      await apiClient.post("/projects/reorder/", payload);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
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
      const response = await apiClient.post<Project>("/projects/", payload);
      return response.data;
    },
    onSuccess: () => {
      setName("");
      setDescription("");
      setIcon("");
      setInitiativeId(null);
      setSelectedTemplateId(NO_TEMPLATE_VALUE);
      setIsTemplateProject(false);
      setIsComposerOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  useEffect(() => {
    localStorage.setItem(PROJECT_SEARCH_KEY, searchQuery);
  }, [searchQuery]);

  useEffect(() => {
    localStorage.setItem(PROJECT_SORT_KEY, sortMode);
  }, [sortMode]);

  useEffect(() => {
    localStorage.setItem(PROJECT_VIEW_KEY, viewMode);
  }, [viewMode]);
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
    const reorderableProjects = (projectsQuery.data ?? []).filter((project) => !project.pinned_at);
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

  const projects = useMemo(() => projectsQuery.data ?? [], [projectsQuery.data]);

  const availableInitiatives = useMemo(() => {
    const map = new Map<number, Initiative>();
    projects.forEach((project) => {
      if (project.initiative) {
        map.set(project.initiative.id, project.initiative);
      }
    });
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [projects]);

  const filteredProjects = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return projects.filter((project) => {
      const matchesSearch = !query ? true : project.name.toLowerCase().includes(query);
      const projectInitiativeId = project.initiative?.id ?? project.initiative_id ?? null;
      const matchesInitiative =
        initiativeFilter === INITIATIVE_FILTER_ALL ||
        (projectInitiativeId !== null &&
          projectInitiativeId !== undefined &&
          initiativeFilter === projectInitiativeId.toString());
      const matchesFavorites = !favoritesOnly ? true : Boolean(project.is_favorited);
      return matchesSearch && matchesInitiative && matchesFavorites;
    });
  }, [projects, searchQuery, initiativeFilter, favoritesOnly]);

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
                <SortableProjectRowLink
                  key={project.id}
                  project={project}
                  canPinProjects={canPinProjects}
                />
              ))}
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {sortedProjects.map((project) => (
                <SortableProjectCardLink
                  key={project.id}
                  project={project}
                  canPinProjects={canPinProjects}
                />
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
              <ProjectRowLink key={project.id} project={project} canPinProjects={canPinProjects} />
            ))}
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {sortedProjects.map((project) => (
              <ProjectCardLink key={project.id} project={project} canPinProjects={canPinProjects} />
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
          Pinned
        </div>

        {viewMode === "list" ? (
          <div className="space-y-3">
            {pinnedProjects.map((project) => (
              <ProjectRowLink
                key={`pinned-${project.id}`}
                project={project}
                canPinProjects={canPinProjects}
              />
            ))}
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {pinnedProjects.map((project) => (
              <ProjectCardLink
                key={`pinned-${project.id}`}
                project={project}
                canPinProjects={canPinProjects}
              />
            ))}
          </div>
        )}
      </div>
    ) : null;

  if (projectsQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading projects…</p>;
  }

  if (projectsQuery.isError) {
    return <p className="text-destructive text-sm">Unable to load projects.</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Projects</h1>
        <p className="text-muted-foreground">Track initiatives and collaborate with your guild.</p>
      </div>

      <Tabs
        value={tabValue}
        onValueChange={(value) => setTabValue(value as "active" | "templates" | "archive")}
        className="space-y-6"
      >
        <TabsList className="w-full justify-start overflow-x-auto">
          <TabsTrigger value="active" className="inline-flex items-center gap-2">
            <LayoutGrid className="h-4 w-4" />
            Active Projects
          </TabsTrigger>
          <TabsTrigger value="templates" className="inline-flex items-center gap-2">
            <ScrollText className="h-4 w-4" />
            Templates
          </TabsTrigger>
          <TabsTrigger value="archive" className="inline-flex items-center gap-2">
            <Archive className="h-4 w-4" />
            Archive
          </TabsTrigger>
        </TabsList>

        <TabsContent value="active" className="space-y-4">
          <div className="flex flex-wrap items-center justify-end gap-3">
            <Tabs
              value={viewMode}
              onValueChange={(value) => setViewMode(value as "grid" | "list")}
              className="w-auto"
            >
              <TabsList className="grid grid-cols-2">
                <TabsTrigger value="grid" className="inline-flex items-center gap-2">
                  <LayoutGrid className="h-4 w-4" />
                  Grid
                </TabsTrigger>
                <TabsTrigger value="list" className="inline-flex items-center gap-2">
                  <List className="h-4 w-4" />
                  List
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
            <div className="flex items-center justify-between sm:hidden">
              <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
                <Filter className="h-4 w-4" />
                Filters
              </div>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="h-8 px-3">
                  {filtersOpen ? "Hide" : "Show"} filters
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
                <div className="w-full lg:flex-1">
                  <Label
                    htmlFor="project-search"
                    className="text-muted-foreground text-xs font-medium"
                  >
                    Filter by name
                  </Label>
                  <Input
                    id="project-search"
                    placeholder="Search projects"
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    className="min-w-60"
                  />
                </div>
                <div className="w-full sm:w-60">
                  <Label
                    htmlFor="project-initiative-filter"
                    className="text-muted-foreground text-xs font-medium"
                  >
                    Filter by initiative
                  </Label>
                  <Select value={initiativeFilter} onValueChange={setInitiativeFilter}>
                    <SelectTrigger id="project-initiative-filter">
                      <SelectValue placeholder="All initiatives" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={INITIATIVE_FILTER_ALL}>All initiatives</SelectItem>
                      {availableInitiatives.map((initiative) => (
                        <SelectItem key={initiative.id} value={initiative.id.toString()}>
                          {initiative.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="w-full sm:w-60">
                  <Label
                    htmlFor="project-sort"
                    className="text-muted-foreground text-xs font-medium"
                  >
                    Sort projects
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
                      <SelectValue placeholder="Select sort order" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="custom">Custom (drag & drop)</SelectItem>
                      <SelectItem value="recently_viewed">Recently opened</SelectItem>
                      <SelectItem value="updated">Recently updated</SelectItem>
                      <SelectItem value="created">Recently created</SelectItem>
                      <SelectItem value="alphabetical">Alphabetical</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="w-full sm:w-60">
                  <Label
                    htmlFor="favorites-only"
                    className="text-muted-foreground text-xs font-medium"
                  >
                    Favorites
                  </Label>
                  <div className="bg-background/60 flex h-10 items-center gap-3 rounded-md border px-3">
                    <Switch
                      id="favorites-only"
                      checked={favoritesOnly}
                      onCheckedChange={(checked) => setFavoritesOnly(Boolean(checked))}
                      aria-label="Filter to favorite projects"
                    />
                    <span className="text-muted-foreground text-sm">Show only favorites</span>
                  </div>
                </div>
              </div>
            </CollapsibleContent>
          </Collapsible>

          {filteredProjects.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {projects.length === 0
                ? "No projects yet. Create one to get started."
                : "No projects match your filters."}
            </p>
          ) : (
            <>
              {pinnedProjectsSection}
              {sortedProjects.length > 0 ? (
                projectCards
              ) : pinnedProjects.length > 0 ? (
                <p className="text-muted-foreground text-sm">
                  Only pinned projects match your filters.
                </p>
              ) : null}
            </>
          )}
        </TabsContent>

        <TabsContent value="templates">
          {templatesQuery.isLoading ? (
            <p className="text-muted-foreground text-sm">Loading templates…</p>
          ) : templatesQuery.isError ? (
            <p className="text-destructive text-sm">Unable to load templates.</p>
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
                    {template.initiative ? <p>Initiative: {template.initiative.name}</p> : null}
                    <p>Last updated: {new Date(template.updated_at).toLocaleString()}</p>
                  </CardContent>
                  <CardFooter className="flex flex-wrap gap-3">
                    <Button asChild variant="link" className="px-0">
                      <Link to={`/projects/${template.id}`}>View template</Link>
                    </Button>
                    {canManageProjects ? (
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => removeTemplate.mutate(template.id)}
                        disabled={removeTemplate.isPending}
                      >
                        Stop using as template
                      </Button>
                    ) : null}
                  </CardFooter>
                </Card>
              ))}
            </div>
          ) : (
            <Card className="shadow-sm">
              <CardHeader>
                <CardTitle>No templates available</CardTitle>
                <CardDescription>
                  Create a template from any project in project settings.
                </CardDescription>
              </CardHeader>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="archive">
          {archivedQuery.isLoading ? (
            <p className="text-muted-foreground text-sm">Loading archived projects…</p>
          ) : archivedQuery.isError ? (
            <p className="text-destructive text-sm">Unable to load archived projects.</p>
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
                    {archived.initiative ? <p>Initiative: {archived.initiative.name}</p> : null}
                    <p>
                      Archived at:{" "}
                      {archived.archived_at
                        ? new Date(archived.archived_at).toLocaleString()
                        : "Unknown"}
                    </p>
                  </CardContent>
                  <CardFooter className="flex flex-wrap gap-3">
                    <Button asChild variant="link" className="px-0">
                      <Link to={`/projects/${archived.id}`}>View details</Link>
                    </Button>
                    {canManageProjects ? (
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => unarchiveProject.mutate(archived.id)}
                        disabled={unarchiveProject.isPending}
                      >
                        Unarchive
                      </Button>
                    ) : null}
                  </CardFooter>
                </Card>
              ))}
            </div>
          ) : (
            <Card className="shadow-sm">
              <CardHeader>
                <CardTitle>No archived projects</CardTitle>
                <CardDescription>Active projects stay on the Active tab.</CardDescription>
              </CardHeader>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      {isProjectManager ? (
        <>
          <Button
            className="shadow-primary/40 fixed right-6 bottom-6 z-40 h-12 rounded-full px-6 shadow-lg"
            onClick={() => setIsComposerOpen(true)}
          >
            <Plus className="mr-2 h-4 w-4" />
            Add Project
          </Button>
          <Dialog open={isComposerOpen} onOpenChange={setIsComposerOpen}>
            <DialogContent className="bg-card">
              <DialogHeader>
                <DialogTitle>Create project</DialogTitle>
                <DialogDescription>
                  Give the project a name, optional description, and owning initiative.
                </DialogDescription>
              </DialogHeader>
              <form className="w-full max-w-lg" onSubmit={handleSubmit}>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="project-icon">Icon (optional)</Label>
                    <EmojiPicker
                      id="project-icon"
                      value={icon || undefined}
                      onChange={(emoji) => setIcon(emoji ?? "")}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="project-name">Name</Label>
                    <Input
                      id="project-name"
                      placeholder="Foundation refresh"
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="project-description">Description (Markdown supported)</Label>
                    <Textarea
                      id="project-description"
                      placeholder="Share context to help the initiative prioritize."
                      rows={3}
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Initiative</Label>
                    {initiativesQuery.isLoading ? (
                      <p className="text-muted-foreground text-sm">Loading initiatives…</p>
                    ) : initiativesQuery.isError ? (
                      <p className="text-destructive text-sm">Unable to load initiatives.</p>
                    ) : initiativesQuery.data && initiativesQuery.data.length > 0 ? (
                      <Select value={initiativeId ?? ""} onValueChange={setInitiativeId}>
                        <SelectTrigger>
                          <SelectValue placeholder="Select initiative" />
                        </SelectTrigger>
                        <SelectContent>
                          {initiativesQuery.data.map((initiative) => (
                            <SelectItem key={initiative.id} value={String(initiative.id)}>
                              {initiative.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <p className="text-muted-foreground text-sm">No initiatives available.</p>
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="project-template">Template (optional)</Label>
                    {templatesQuery.isLoading ? (
                      <p className="text-muted-foreground text-sm">Loading templates…</p>
                    ) : templatesQuery.isError ? (
                      <p className="text-destructive text-sm">Unable to load templates.</p>
                    ) : (
                      <Select
                        value={selectedTemplateId}
                        onValueChange={setSelectedTemplateId}
                        disabled={isTemplateProject}
                      >
                        <SelectTrigger id="project-template">
                          <SelectValue placeholder="No template" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={NO_TEMPLATE_VALUE}>No template</SelectItem>
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
                        Disable &ldquo;Save as template&rdquo; to pick a template.
                      </p>
                    ) : null}
                  </div>
                  <div className="bg-muted/20 flex items-center justify-between rounded-lg border p-3">
                    <div>
                      <Label htmlFor="create-as-template" className="text-base">
                        Save as template
                      </Label>
                      <p className="text-muted-foreground text-xs">
                        Template projects live under the Templates tab and can be reused to spin up
                        new work.
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
                  <div className="flex flex-wrap gap-2">
                    <Button type="submit" disabled={createProject.isPending}>
                      {createProject.isPending ? "Creating…" : "Create project"}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={createProject.isPending}
                      onClick={() => setIsComposerOpen(false)}
                    >
                      Cancel
                    </Button>
                    {createProject.isError ? (
                      <p className="text-destructive text-sm">Unable to create project.</p>
                    ) : null}
                  </div>
                </div>
              </form>
            </DialogContent>
          </Dialog>
        </>
      ) : null}
    </div>
  );
};

const ProjectCardLink = ({
  project,
  dragHandleProps,
  canPinProjects,
}: {
  project: Project;
  dragHandleProps?: HTMLAttributes<HTMLButtonElement>;
  canPinProjects: boolean;
}) => {
  const initiative = project.initiative;
  const initiativeColor = initiative ? resolveInitiativeColor(initiative.color) : null;
  const isPinned = Boolean(project.pinned_at);

  return (
    <div className="relative">
      <div className="absolute top-4 right-4 z-10 flex items-center gap-2">
        <PinProjectButton
          projectId={project.id}
          isPinned={isPinned}
          canPin={canPinProjects}
          suppressNavigation
        />
        <FavoriteProjectButton
          projectId={project.id}
          isFavorited={project.is_favorited ?? false}
          suppressNavigation
        />
        {dragHandleProps ? (
          <button
            type="button"
            className="bg-background text-muted-foreground hover:text-foreground focus-visible:ring-ring rounded-full border p-1 transition focus-visible:ring-2 focus-visible:outline-none"
            aria-label="Reorder project"
            {...dragHandleProps}
          >
            <GripVertical className="h-4 w-4" />
          </button>
        ) : null}
      </div>
      <Link to={`/projects/${project.id}`} className="block">
        <Card className="overflow-hidden shadow-sm">
          {initiativeColor ? (
            <div
              className="h-1.5 w-full"
              style={{ backgroundColor: initiativeColor }}
              aria-hidden="true"
            />
          ) : null}
          <CardHeader className="pr-22">
            <CardTitle className="flex items-center gap-2 text-xl">
              {project.icon ? <span className="text-2xl leading-none">{project.icon}</span> : null}
              <span>{project.name}</span>
            </CardTitle>
          </CardHeader>
          <CardFooter className="text-muted-foreground flex justify-between gap-6 space-y-2 text-sm">
            <div>
              <InitiativeLabel initiative={initiative} />
              <p>Updated {new Date(project.updated_at).toLocaleDateString(undefined)}</p>
            </div>

            <div className="flex-1">
              <ProjectProgress summary={project.task_summary} />
            </div>
          </CardFooter>
        </Card>
      </Link>
    </div>
  );
};

const SortableProjectCardLink = ({
  project,
  canPinProjects,
}: {
  project: Project;
  canPinProjects: boolean;
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
      <ProjectCardLink
        project={project}
        dragHandleProps={dragHandleProps}
        canPinProjects={canPinProjects}
      />
    </div>
  );
};

const ProjectRowLink = ({
  project,
  dragHandleProps,
  canPinProjects,
}: {
  project: Project;
  dragHandleProps?: HTMLAttributes<HTMLButtonElement>;
  canPinProjects: boolean;
}) => {
  const initiativeColor = project.initiative
    ? resolveInitiativeColor(project.initiative.color)
    : null;
  const isPinned = Boolean(project.pinned_at);
  return (
    <div className="relative">
      {dragHandleProps ? (
        <button
          type="button"
          className="bg-background text-muted-foreground hover:text-foreground focus-visible:ring-ring absolute top-1/2 left-4 z-10 -translate-y-1/2 rounded-full border p-1 transition focus-visible:ring-2 focus-visible:outline-none"
          aria-label="Reorder project"
          {...dragHandleProps}
        >
          <GripVertical className="h-4 w-4" />
        </button>
      ) : null}
      <div className="absolute top-4 right-4 z-10">
        <div className="flex items-center gap-2">
          <PinProjectButton
            projectId={project.id}
            isPinned={isPinned}
            canPin={canPinProjects}
            suppressNavigation
            iconSize="sm"
          />
          <FavoriteProjectButton
            projectId={project.id}
            isFavorited={project.is_favorited ?? false}
            suppressNavigation
            iconSize="sm"
          />
        </div>
      </div>
      <Link to={`/projects/${project.id}`} className="block">
        <Card
          className={`p-4 pr-16 shadow-sm ${initiativeColor ? "border-l-4" : ""}`}
          style={initiativeColor ? { borderLeftColor: initiativeColor } : undefined}
        >
          <div className={`flex flex-wrap items-center gap-4 ${dragHandleProps ? "pl-10" : ""}`}>
            {project.icon ? <span className="text-2xl leading-none">{project.icon}</span> : null}
            <div className="min-w-[200px] flex-1">
              <p className="font-semibold">{project.name}</p>
              <div className="flex flex-wrap gap-6">
                <div className="min-w-30 flex-1">
                  <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-3 text-xs">
                    <p>Updated {new Date(project.updated_at).toLocaleDateString(undefined)}</p>
                    <InitiativeLabel initiative={project.initiative} />
                  </div>
                </div>
                <div className="flex-1">
                  <ProjectProgress summary={project.task_summary} />
                </div>
              </div>
            </div>
          </div>
        </Card>
      </Link>
    </div>
  );
};

const SortableProjectRowLink = ({
  project,
  canPinProjects,
}: {
  project: Project;
  canPinProjects: boolean;
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
      <ProjectRowLink
        project={project}
        dragHandleProps={dragHandleProps}
        canPinProjects={canPinProjects}
      />
    </div>
  );
};

const InitiativeLabel = ({ initiative }: { initiative?: Initiative | null }) => {
  if (!initiative) {
    return null;
  }
  return (
    <span className="text-muted-foreground flex items-center gap-2 text-xs font-medium">
      <InitiativeColorDot color={initiative.color} />
      <span>{initiative.name}</span>
    </span>
  );
};

const ProjectProgress = ({ summary }: { summary?: Project["task_summary"] }) => {
  const total = summary?.total ?? 0;
  const completed = summary?.completed ?? 0;
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div className="@container flex w-full items-center justify-between gap-4">
      <div className="hidden w-full flex-col gap-2 @xs:flex">
        <span className="text-muted-foreground flex justify-end text-xs">
          {completed}/{total} done
        </span>
        <Progress value={percent} className="h-2" />
      </div>
      <div className="flex w-full items-center justify-end gap-3 @xs:hidden">
        <ProgressCircle value={percent} />
      </div>
    </div>
  );
};
