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
import { GripVertical } from "lucide-react";

import { apiClient } from "../api/client";
import { Markdown } from "../components/Markdown";
import { FavoriteProjectButton } from "../components/projects/FavoriteProjectButton";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { Textarea } from "../components/ui/textarea";
import { EmojiPicker } from "../components/EmojiPicker";
import { Switch } from "../components/ui/switch";
import { useAuth } from "../hooks/useAuth";
import { queryClient } from "../lib/queryClient";
import { InitiativeColorDot, resolveInitiativeColor } from "../lib/initiativeColors";
import { Project, ProjectReorderPayload, Initiative } from "../types/api";

const NO_INITIATIVE_VALUE = "none";
const NO_TEMPLATE_VALUE = "template-none";
const INITIATIVE_FILTER_ALL = "all";
const INITIATIVE_FILTER_UNASSIGNED = "unassigned";
const PROJECT_SORT_KEY = "project:list:sort";
const PROJECT_SEARCH_KEY = "project:list:search";
const PROJECT_VIEW_KEY = "project:list:view-mode";

export const ProjectsPage = () => {
  const { user } = useAuth();
  const canManageProjects =
    user?.role === "admin" || user?.role === "project_manager";
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [icon, setIcon] = useState("");
  const [initiativeId, setInitiativeId] = useState<string>(NO_INITIATIVE_VALUE);
  const [isComposerOpen, setIsComposerOpen] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>(
    NO_TEMPLATE_VALUE
  );
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
      void queryClient.invalidateQueries({ queryKey: ["projects", "templates"] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const [initiativeFilter, setInitiativeFilter] = useState<string>(
    INITIATIVE_FILTER_ALL
  );
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const unarchiveProject = useMutation({
    mutationFn: async (projectId: number) => {
      await apiClient.post(`/projects/${projectId}/unarchive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects", "archived"] });
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
  const [tabValue, setTabValue] = useState<"active" | "templates" | "archive">(
    "active"
  );

  const projectsQuery = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/");
      return response.data;
    },
  });

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: ["initiatives"],
    enabled: user?.role === "admin",
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
  });

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

  const reorderProjects = useMutation({
    mutationFn: async (orderedIds: number[]) => {
      const payload: ProjectReorderPayload = { project_ids: orderedIds };
      await apiClient.post("/projects/reorder", payload);
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
      if (user?.role === "admin" && initiativeId !== NO_INITIATIVE_VALUE) {
        payload.initiative_id = Number(initiativeId);
      }
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
      setInitiativeId(NO_INITIATIVE_VALUE);
      setSelectedTemplateId(NO_TEMPLATE_VALUE);
      setIsTemplateProject(false);
      setIsComposerOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({ queryKey: ["projects", "templates"] });
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
    const template = templatesQuery.data?.find(
      (item) => item.id === templateId
    );
    if (!template) {
      return;
    }
    setDescription(template.description ?? "");
  }, [selectedTemplateId, templatesQuery.data, isTemplateProject]);

  useEffect(() => {
    const projects = projectsQuery.data ?? [];
    if (projects.length === 0) {
      setCustomOrder((prev) => (prev.length ? [] : prev));
      return;
    }
    const projectIds = projects.map((project) => project.id);
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

  const projects = useMemo(
    () => projectsQuery.data ?? [],
    [projectsQuery.data]
  );

  const availableInitiatives = useMemo(() => {
    const map = new Map<number, Initiative>();
    projects.forEach((project) => {
      if (project.initiative) {
        map.set(project.initiative.id, project.initiative);
      }
    });
    return Array.from(map.values()).sort((a, b) =>
      a.name.localeCompare(b.name)
    );
  }, [projects]);

  const filteredProjects = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return projects.filter((project) => {
      const matchesSearch = !query
        ? true
        : project.name.toLowerCase().includes(query);
      const projectInitiativeId =
        project.initiative?.id ?? project.initiative_id ?? null;
      const matchesInitiative =
        initiativeFilter === INITIATIVE_FILTER_ALL ||
        (initiativeFilter === INITIATIVE_FILTER_UNASSIGNED &&
          (projectInitiativeId === null || projectInitiativeId === undefined)) ||
        (projectInitiativeId !== null &&
          projectInitiativeId !== undefined &&
          initiativeFilter === projectInitiativeId.toString());
      const matchesFavorites = !favoritesOnly
        ? true
        : Boolean(project.is_favorited);
      return matchesSearch && matchesInitiative && matchesFavorites;
    });
  }, [projects, searchQuery, initiativeFilter, favoritesOnly]);

  const sortedProjects = useMemo(() => {
    const next = [...filteredProjects];
    if (sortMode === "alphabetical") {
      next.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortMode === "created") {
      next.sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      );
    } else if (sortMode === "updated") {
      next.sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      );
    } else if (sortMode === "recently_viewed") {
      next.sort((a, b) => {
        const aViewed = a.last_viewed_at
          ? new Date(a.last_viewed_at).getTime()
          : 0;
        const bViewed = b.last_viewed_at
          ? new Date(b.last_viewed_at).getTime()
          : 0;
        if (aViewed === bViewed) {
          return (
            new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
          );
        }
        return bViewed - aViewed;
      });
    } else {
      const orderMap = new Map<number, number>();
      customOrder.forEach((id, index) => orderMap.set(id, index));
      next.sort((a, b) => {
        const aIndex = orderMap.has(a.id)
          ? orderMap.get(a.id)!
          : Number.MAX_SAFE_INTEGER;
        const bIndex = orderMap.has(b.id)
          ? orderMap.get(b.id)!
          : Number.MAX_SAFE_INTEGER;
        return aIndex - bIndex;
      });
    }
    return next;
  }, [filteredProjects, sortMode, customOrder]);

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
                <SortableProjectRowLink key={project.id} project={project} />
              ))}
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {sortedProjects.map((project) => (
                <SortableProjectCardLink key={project.id} project={project} />
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
              <ProjectRowLink key={project.id} project={project} />
            ))}
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {sortedProjects.map((project) => (
              <ProjectCardLink key={project.id} project={project} />
            ))}
          </div>
        )}
      </>
    );

  if (projectsQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading projects…</p>;
  }

  if (projectsQuery.isError) {
    return <p className="text-sm text-destructive">Unable to load projects.</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Projects</h1>
        <p className="text-muted-foreground">
          Track initiatives, collaborate with your organization, and move work forward.
        </p>
      </div>

      <Tabs
        value={tabValue}
        onValueChange={(value) =>
          setTabValue(value as "active" | "templates" | "archive")
        }
        className="space-y-6"
      >
        <TabsList>
          <TabsTrigger value="active">Active Projects</TabsTrigger>
          <TabsTrigger value="templates">Templates</TabsTrigger>
          <TabsTrigger value="archive">Archive</TabsTrigger>
        </TabsList>

        <TabsContent value="active" className="space-y-4">
          <div className="space-y-4 rounded-md border border-muted/70 bg-card/30 p-4">
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
              <div className="space-y-1 md:col-span-2 xl:col-span-2">
                <Label htmlFor="project-search">Filter by name</Label>
                <Input
                  id="project-search"
                  placeholder="Search projects"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="project-initiative-filter">
                  Filter by initiative
                </Label>
                <Select
                  value={initiativeFilter}
                  onValueChange={setInitiativeFilter}
                >
                  <SelectTrigger id="project-initiative-filter">
                    <SelectValue placeholder="All initiatives" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={INITIATIVE_FILTER_ALL}>
                      All initiatives
                    </SelectItem>
                    <SelectItem value={INITIATIVE_FILTER_UNASSIGNED}>
                      No initiative
                    </SelectItem>
                    {availableInitiatives.map((initiative) => (
                      <SelectItem
                        key={initiative.id}
                        value={initiative.id.toString()}
                      >
                        {initiative.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="project-sort">Sort projects</Label>
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
                    <SelectItem value="recently_viewed">
                      Recently opened
                    </SelectItem>
                    <SelectItem value="updated">Recently updated</SelectItem>
                    <SelectItem value="created">Recently created</SelectItem>
                    <SelectItem value="alphabetical">Alphabetical</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="project-view">View</Label>
                <Select
                  value={viewMode}
                  onValueChange={(value) =>
                    setViewMode(value as "grid" | "list")
                  }
                >
                  <SelectTrigger id="project-view">
                    <SelectValue placeholder="Select view" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="grid">Card view</SelectItem>
                    <SelectItem value="list">List view</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="favorites-only">Favorites</Label>
                <div className="flex h-10 items-center gap-3 rounded-md border bg-background/60 px-3">
                  <Switch
                    id="favorites-only"
                    checked={favoritesOnly}
                    onCheckedChange={(checked) =>
                      setFavoritesOnly(Boolean(checked))
                    }
                    aria-label="Filter to favorite projects"
                  />
                  <span className="text-sm text-muted-foreground">
                    Show only favorites
                  </span>
                </div>
              </div>
            </div>
          </div>
          {sortedProjects.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {projects.length === 0
                ? "No projects yet. Create one to get started."
                : "No projects match your filters."}
            </p>
          ) : (
            projectCards
          )}
        </TabsContent>

        <TabsContent value="templates">
          {templatesQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading templates…</p>
          ) : templatesQuery.isError ? (
            <p className="text-sm text-destructive">Unable to load templates.</p>
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
                  <CardContent className="space-y-2 text-sm text-muted-foreground">
                    {template.initiative ? <p>Initiative: {template.initiative.name}</p> : null}
                    <p>
                      Last updated: {new Date(template.updated_at).toLocaleString()}
                    </p>
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
            <p className="text-sm text-muted-foreground">Loading archived projects…</p>
          ) : archivedQuery.isError ? (
            <p className="text-sm text-destructive">Unable to load archived projects.</p>
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
                  <CardContent className="space-y-2 text-sm text-muted-foreground">
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
                <CardDescription>
                  Active projects stay on the Active tab.
                </CardDescription>
              </CardHeader>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      {canManageProjects ? (
        <>
          <Button
            className="fixed bottom-6 right-6 z-40 h-12 rounded-full px-6 shadow-lg shadow-primary/40"
            onClick={() => setIsComposerOpen(true)}
          >
            Add Project
          </Button>
          {isComposerOpen ? (
            <div className="fixed inset-0 z-50 flex items-end justify-center bg-background/70 p-4 backdrop-blur-sm sm:items-center">
              <div
                className="absolute inset-0 -z-10"
                role="presentation"
                onClick={() => setIsComposerOpen(false)}
              />
              <form className="w-full max-w-lg" onSubmit={handleSubmit}>
                <Card className="rounded-2xl border shadow-2xl">
                  <CardHeader>
                    <CardTitle>Create project</CardTitle>
                    <CardDescription>
                      Give the project a name, optional description, and owning initiative.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
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
                      <Label htmlFor="project-description">
                        Description (Markdown supported)
                      </Label>
                      <Textarea
                        id="project-description"
                        placeholder="Share context to help the initiative prioritize."
                        rows={3}
                        value={description}
                        onChange={(event) => setDescription(event.target.value)}
                      />
                    </div>
                    {user?.role === "admin" ? (
                      <div className="space-y-2">
                        <Label>Initiative (optional)</Label>
                        {initiativesQuery.isLoading ? (
                          <p className="text-sm text-muted-foreground">
                            Loading initiatives…
                          </p>
                        ) : initiativesQuery.isError ? (
                          <p className="text-sm text-destructive">
                            Unable to load initiatives.
                          </p>
                        ) : (
                          <Select value={initiativeId} onValueChange={setInitiativeId}>
                            <SelectTrigger>
                              <SelectValue placeholder="No initiative" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value={NO_INITIATIVE_VALUE}>No initiative</SelectItem>
                              {initiativesQuery.data?.map((initiative) => (
                                <SelectItem key={initiative.id} value={String(initiative.id)}>
                                  {initiative.name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        )}
                      </div>
                    ) : null}
                    <div className="space-y-2">
                      <Label htmlFor="project-template">Template (optional)</Label>
                      {templatesQuery.isLoading ? (
                        <p className="text-sm text-muted-foreground">
                          Loading templates…
                        </p>
                      ) : templatesQuery.isError ? (
                        <p className="text-sm text-destructive">
                          Unable to load templates.
                        </p>
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
                            <SelectItem value={NO_TEMPLATE_VALUE}>
                              No template
                            </SelectItem>
                            {templatesQuery.data?.map((template) => (
                              <SelectItem
                                key={template.id}
                                value={String(template.id)}
                              >
                                {template.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      )}
                      {isTemplateProject ? (
                        <p className="text-xs text-muted-foreground">
                          Disable &ldquo;Save as template&rdquo; to pick a template.
                        </p>
                      ) : null}
                    </div>
                    <div className="flex items-center justify-between rounded-lg border bg-muted/20 p-3">
                      <div>
                        <Label htmlFor="create-as-template" className="text-base">
                          Save as template
                        </Label>
                        <p className="text-xs text-muted-foreground">
                          Template projects live under the Templates tab and can
                          be reused to spin up new work.
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
                        {createProject.isPending
                          ? "Creating…"
                          : "Create project"}
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
                        <p className="text-sm text-destructive">
                          Unable to create project.
                        </p>
                      ) : null}
                    </div>
                  </CardContent>
                </Card>
              </form>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
};

const ProjectCardLink = ({
  project,
  dragHandleProps,
}: {
  project: Project;
  dragHandleProps?: HTMLAttributes<HTMLButtonElement>;
}) => {
  const initiative = project.initiative;
  const initiativeColor = initiative ? resolveInitiativeColor(initiative.color) : null;

  return (
    <div className="relative">
      <div className="absolute right-4 top-4 z-10 flex items-center gap-2">
        <FavoriteProjectButton
          projectId={project.id}
          isFavorited={project.is_favorited ?? false}
          suppressNavigation
        />
        {dragHandleProps ? (
          <button
            type="button"
            className="rounded-full border bg-background p-1 text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-xl">
              {project.icon ? (
                <span className="text-2xl leading-none">{project.icon}</span>
              ) : null}
              <span>{project.name}</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <InitiativeLabel initiative={initiative} />
            <p>
              Updated {new Date(project.updated_at).toLocaleDateString(undefined)}
            </p>
          </CardContent>
        </Card>
      </Link>
    </div>
  );
};

const SortableProjectCardLink = ({ project }: { project: Project }) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({
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
    <div
      ref={setNodeRef}
      style={style}
      className={isDragging ? "opacity-70" : undefined}
    >
      <ProjectCardLink project={project} dragHandleProps={dragHandleProps} />
    </div>
  );
};

const ProjectRowLink = ({
  project,
  dragHandleProps,
}: {
  project: Project;
  dragHandleProps?: HTMLAttributes<HTMLButtonElement>;
}) => {
  const initiativeColor = project.initiative
    ? resolveInitiativeColor(project.initiative.color)
    : null;
  return (
    <div className="relative">
      {dragHandleProps ? (
        <button
          type="button"
          className="absolute left-4 top-1/2 z-10 -translate-y-1/2 rounded-full border bg-background p-1 text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Reorder project"
          {...dragHandleProps}
        >
          <GripVertical className="h-4 w-4" />
        </button>
      ) : null}
      <div className="absolute right-4 top-4 z-10">
        <FavoriteProjectButton
          projectId={project.id}
          isFavorited={project.is_favorited ?? false}
          suppressNavigation
          iconSize="sm"
        />
      </div>
      <Link to={`/projects/${project.id}`} className="block">
        <Card
          className={`shadow-sm p-4 pr-16 ${initiativeColor ? "border-l-4" : ""}`}
          style={initiativeColor ? { borderLeftColor: initiativeColor } : undefined}
        >
          <div
            className={`flex flex-wrap items-center gap-4 ${
              dragHandleProps ? "pl-10" : ""
            }`}
          >
            {project.icon ? (
              <span className="text-2xl leading-none">{project.icon}</span>
            ) : null}
            <div className="flex-1 min-w-[200px]">
              <p className="font-semibold">{project.name}</p>
              <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                <p>
                  Updated {new Date(project.updated_at).toLocaleDateString(undefined)}
                </p>
                <InitiativeLabel initiative={project.initiative} />
              </div>
            </div>
          </div>
        </Card>
      </Link>
    </div>
  );
};

const SortableProjectRowLink = ({ project }: { project: Project }) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({
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
    <div
      ref={setNodeRef}
      style={style}
      className={isDragging ? "opacity-70" : undefined}
    >
      <ProjectRowLink project={project} dragHandleProps={dragHandleProps} />
    </div>
  );
};

const InitiativeLabel = ({ initiative }: { initiative?: Initiative | null }) => {
  if (!initiative) {
    return null;
  }
  return (
    <span className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
      <InitiativeColorDot color={initiative.color} />
      <span>{initiative.name}</span>
    </span>
  );
};
