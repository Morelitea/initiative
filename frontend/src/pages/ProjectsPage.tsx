import { FormEvent, HTMLAttributes, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  DndContext,
  DragEndEvent,
  PointerSensor,
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
import { Badge } from "../components/ui/badge";
import { Switch } from "../components/ui/switch";
import { useAuth } from "../hooks/useAuth";
import { queryClient } from "../lib/queryClient";
import { Project, Team } from "../types/api";

const NO_TEAM_VALUE = "none";
const NO_TEMPLATE_VALUE = "template-none";
const PROJECT_SORT_KEY = "project:list:sort";
const PROJECT_ORDER_KEY = "project:list:custom-order";
const PROJECT_SEARCH_KEY = "project:list:search";
const PROJECT_VIEW_KEY = "project:list:view-mode";

export const ProjectsPage = () => {
  const { user } = useAuth();
  const canManageProjects =
    user?.role === "admin" || user?.role === "project_manager";
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [icon, setIcon] = useState("");
  const [teamId, setTeamId] = useState<string>(NO_TEAM_VALUE);
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
    "custom" | "updated" | "created" | "alphabetical"
  >(() => {
    if (typeof window === "undefined") {
      return "custom";
    }
    const stored = localStorage.getItem(PROJECT_SORT_KEY);
    if (
      stored === "custom" ||
      stored === "updated" ||
      stored === "created" ||
      stored === "alphabetical"
    ) {
      return stored;
    }
    return "custom";
  });
  const [customOrder, setCustomOrder] = useState<number[]>(() => {
    if (typeof window === "undefined") {
      return [];
    }
    try {
      const stored = localStorage.getItem(PROJECT_ORDER_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) {
          return parsed.filter((value) => Number.isFinite(value));
        }
      }
    } catch {
      /* ignore */
    }
    return [];
  });
  const removeTemplate = useMutation({
    mutationFn: async (projectId: number) => {
      await apiClient.patch(`/projects/${projectId}`, { is_template: false });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects", "templates"] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

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

  const teamsQuery = useQuery<Team[]>({
    queryKey: ["teams"],
    enabled: user?.role === "admin",
    queryFn: async () => {
      const response = await apiClient.get<Team[]>("/teams/");
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


  const createProject = useMutation({
    mutationFn: async () => {
      const payload: {
        name: string;
        description: string;
        icon?: string;
        team_id?: number;
        template_id?: number;
        is_template?: boolean;
      } = { name, description };
      const trimmedIcon = icon.trim();
      if (trimmedIcon) {
        payload.icon = trimmedIcon;
      }
      if (user?.role === "admin" && teamId !== NO_TEAM_VALUE) {
        payload.team_id = Number(teamId);
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
      setTeamId(NO_TEAM_VALUE);
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
    localStorage.setItem(PROJECT_ORDER_KEY, JSON.stringify(customOrder));
  }, [customOrder]);

  useEffect(() => {
    localStorage.setItem(PROJECT_VIEW_KEY, viewMode);
  }, [viewMode]);

  useEffect(() => {
    const projects = projectsQuery.data ?? [];
    if (projects.length === 0) {
      setCustomOrder((prev) => (prev.length ? [] : prev));
      return;
    }
    setCustomOrder((prev) => {
      const projectIds = projects.map((project) => project.id);
      const existing = prev.filter((id) => projectIds.includes(id));
      const missing = projectIds.filter((id) => !existing.includes(id));
      if (missing.length === 0 && existing.length === prev.length) {
        return prev;
      }
      return [...existing, ...missing];
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

  const filteredProjects = useMemo(() => {
    if (!searchQuery.trim()) {
      return projects;
    }
    const query = searchQuery.trim().toLowerCase();
    return projects.filter((project) =>
      project.name.toLowerCase().includes(query)
    );
  }, [projects, searchQuery]);

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
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

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
      return arrayMove(prev, oldIndex, newIndex);
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
          Track initiatives, collaborate with your team, and move work forward.
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
          <div className="flex flex-col gap-4 rounded-md border border-muted/70 bg-card/30 p-4 md:flex-row md:items-end">
            <div className="flex-1 space-y-1">
              <Label htmlFor="project-search">Filter by name</Label>
              <Input
                id="project-search"
                placeholder="Search projects"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </div>
            <div className="w-full space-y-1 md:w-64">
              <Label htmlFor="project-sort">Sort projects</Label>
              <Select
                value={sortMode}
                onValueChange={(value) =>
                  setSortMode(
                    value as "custom" | "updated" | "created" | "alphabetical"
                  )
                }
              >
                <SelectTrigger id="project-sort">
                  <SelectValue placeholder="Select sort order" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="custom">Custom (drag & drop)</SelectItem>
                  <SelectItem value="updated">Recently updated</SelectItem>
                  <SelectItem value="created">Recently created</SelectItem>
                  <SelectItem value="alphabetical">Alphabetical</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="w-full space-y-1 md:w-48">
              <Label htmlFor="project-view">View</Label>
              <Select
                value={viewMode}
                onValueChange={(value) => setViewMode(value as "grid" | "list")}
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
          </div>
          {sortedProjects.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {projects.length === 0
                ? "No projects yet. Create one to get started."
                : "No projects match your search."}
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
                    {template.team ? <p>Team: {template.team.name}</p> : null}
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
                    {archived.team ? <p>Team: {archived.team.name}</p> : null}
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
                      Give the project a name, optional description, and owning
                      team.
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
                        placeholder="Share context to help the team prioritize."
                        rows={3}
                        value={description}
                        onChange={(event) => setDescription(event.target.value)}
                      />
                    </div>
                    {user?.role === "admin" ? (
                      <div className="space-y-2">
                        <Label>Team (optional)</Label>
                        {teamsQuery.isLoading ? (
                          <p className="text-sm text-muted-foreground">
                            Loading teams…
                          </p>
                        ) : teamsQuery.isError ? (
                          <p className="text-sm text-destructive">
                            Unable to load teams.
                          </p>
                    ) : (
                      <Select value={teamId} onValueChange={setTeamId}>
                        <SelectTrigger>
                          <SelectValue placeholder="No team" />
                        </SelectTrigger>
                            <SelectContent>
                              <SelectItem value={NO_TEAM_VALUE}>
                                No team
                              </SelectItem>
                              {teamsQuery.data?.map((team) => (
                                <SelectItem
                                  key={team.id}
                                  value={String(team.id)}
                                >
                                  {team.name}
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
}) => (
  <div className="relative">
    {dragHandleProps ? (
      <button
        type="button"
        className="absolute right-4 top-4 z-10 rounded-full border bg-background p-1 text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="Reorder project"
        {...dragHandleProps}
      >
        <GripVertical className="h-4 w-4" />
      </button>
    ) : null}
    <Link to={`/projects/${project.id}`} className="block">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-xl">
            {project.icon ? (
              <span className="text-2xl leading-none">{project.icon}</span>
            ) : null}
          <span>{project.name}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm text-muted-foreground">
        {project.team ? <Badge>Team: {project.team.name}</Badge> : null}
        <p>
          Updated {new Date(project.updated_at).toLocaleDateString(undefined)}
        </p>
      </CardContent>
    </Card>
    </Link>
  </div>
);

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
}) => (
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
    <Link to={`/projects/${project.id}`} className="block">
      <Card className="shadow-sm p-4">
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
            <p className="text-xs text-muted-foreground">
              Updated {new Date(project.updated_at).toLocaleDateString(undefined)}
            </p>
          </div>
          {project.team ? <Badge>Team: {project.team.name}</Badge> : null}
        </div>
      </Card>
    </Link>
  </div>
);

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
