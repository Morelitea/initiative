import { useMemo, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LayoutGrid, List, Loader2, Settings } from "lucide-react";

import { apiClient } from "@/api/client";
import { DocumentsView } from "./DocumentsPage";
import { ProjectCardLink, ProjectRowLink } from "@/components/projects/ProjectPreview";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { getRoleLabel, useRoleLabels } from "@/hooks/useRoleLabels";
import { Markdown } from "@/components/Markdown";
import type { Initiative, Project } from "@/types/api";

export const InitiativeDetailPage = () => {
  const { initiativeId: initiativeIdParam } = useParams();
  const parsedInitiativeId = Number(initiativeIdParam);
  const hasValidInitiativeId = Number.isFinite(parsedInitiativeId);
  const initiativeId = hasValidInitiativeId ? parsedInitiativeId : 0;
  const { user } = useAuth();
  const { activeGuild } = useGuilds();
  const { data: roleLabels } = useRoleLabels();
  const projectManagerLabel = getRoleLabel("project_manager", roleLabels);
  const memberLabel = getRoleLabel("member", roleLabels);
  const guildAdminLabel = getRoleLabel("admin", roleLabels);

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: ["initiatives"],
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
    enabled: hasValidInitiativeId,
  });

  const projectsQuery = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/");
      return response.data;
    },
    enabled: hasValidInitiativeId,
  });

  const initiative =
    hasValidInitiativeId && initiativesQuery.data
      ? (initiativesQuery.data.find((item) => item.id === initiativeId) ?? null)
      : null;
  const isGuildAdmin = user?.role === "admin" || activeGuild?.role === "admin";
  const membership = initiative?.members.find((member) => member.user.id === user?.id) ?? null;
  const isInitiativeManager = membership?.role === "project_manager";
  const canManageInitiative = Boolean(isGuildAdmin || isInitiativeManager);
  const canPinProjects = Boolean(user?.role === "admin" || isInitiativeManager);

  const [activeTab, setActiveTab] = useState<"documents" | "projects">("documents");
  const [projectSearch, setProjectSearch] = useState("");
  const [projectView, setProjectView] = useState<"grid" | "list">("grid");

  const filteredProjects = useMemo(() => {
    if (!hasValidInitiativeId || !projectsQuery.data) {
      return [];
    }
    return projectsQuery.data.filter(
      (project) =>
        project.initiative_id === initiativeId && !project.is_archived && !project.is_template
    );
  }, [projectsQuery.data, initiativeId, hasValidInitiativeId]);

  const visibleProjects = useMemo(() => {
    const normalizedSearch = projectSearch.trim().toLowerCase();
    const byUpdated = filteredProjects
      .slice()
      .sort(
        (a, b) =>
          Number(Boolean(b.pinned_at)) - Number(Boolean(a.pinned_at)) ||
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      );
    if (!normalizedSearch) {
      return byUpdated;
    }
    return byUpdated.filter((project) => project.name.toLowerCase().includes(normalizedSearch));
  }, [filteredProjects, projectSearch]);

  const memberCount = initiative?.members.length ?? 0;
  const projectCount = filteredProjects.length;

  const roleBadgeLabel = membership
    ? membership.role === "project_manager"
      ? projectManagerLabel
      : memberLabel
    : isGuildAdmin
      ? guildAdminLabel
      : null;

  if (!hasValidInitiativeId) {
    return <Navigate to="/initiatives" replace />;
  }

  if (initiativesQuery.isLoading || !initiativesQuery.data) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading initiative…
      </div>
    );
  }

  if (!initiative) {
    return (
      <div className="space-y-4">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to="/initiatives">← Back to My Initiatives</Link>
        </Button>
        <div className="rounded-lg border p-6">
          <h1 className="text-2xl font-semibold">Initiative not found</h1>
          <p className="text-muted-foreground">
            The initiative you&apos;re looking for doesn&apos;t exist or you no longer have access.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-4">
          <Button variant="link" size="sm" asChild className="px-0">
            <Link to="/initiatives">← Back to My Initiatives</Link>
          </Button>
          <div className="flex flex-wrap items-center gap-3">
            <InitiativeColorDot color={initiative.color} className="h-4 w-4" />
            <h1 className="text-3xl font-semibold tracking-tight">{initiative.name}</h1>
            {initiative.is_default ? <Badge variant="outline">Default</Badge> : null}
            {roleBadgeLabel ? <Badge variant="secondary">{roleBadgeLabel}</Badge> : null}
          </div>
          {initiative.description ? (
            <Markdown content={initiative.description} className="text-muted-foreground" />
          ) : (
            <p className="text-muted-foreground text-sm">No description yet.</p>
          )}
          <div className="text-muted-foreground flex flex-wrap items-center gap-4 text-sm">
            <span>
              {memberCount} {memberCount === 1 ? "member" : "members"}
            </span>
            <span>
              {projectCount} {projectCount === 1 ? "project" : "projects"}
            </span>
            <span>Updated {new Date(initiative.updated_at).toLocaleDateString()}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {canManageInitiative ? (
            <Button variant="outline" asChild>
              <Link to={`/initiatives/${initiative.id}/settings`}>
                <Settings className="mr-2 h-4 w-4" />
                Initiative settings
              </Link>
            </Button>
          ) : null}
        </div>
      </div>

      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as "documents" | "projects")}
      >
        <TabsList className="grid w-full max-w-xs grid-cols-2">
          <TabsTrigger value="documents">Documents</TabsTrigger>
          <TabsTrigger value="projects">Projects</TabsTrigger>
        </TabsList>
        <TabsContent value="documents" className="mt-6">
          <DocumentsView key={`documents-${initiative.id}`} fixedInitiativeId={initiative.id} />
        </TabsContent>
        <TabsContent value="projects" className="mt-6 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-[220px] flex-1 space-y-1">
              <Label htmlFor="initiative-project-search" className="text-muted-foreground text-xs">
                Search projects
              </Label>
              <Input
                id="initiative-project-search"
                value={projectSearch}
                onChange={(event) => setProjectSearch(event.target.value)}
                placeholder="Search by name"
              />
            </div>
            <Tabs
              value={projectView}
              onValueChange={(value) => setProjectView(value as "grid" | "list")}
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
          {projectsQuery.isLoading ? (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading projects…
            </div>
          ) : null}
          {projectsQuery.isError ? (
            <p className="text-destructive text-sm">Unable to load projects right now.</p>
          ) : null}
          {!projectsQuery.isLoading && !projectsQuery.isError ? (
            visibleProjects.length > 0 ? (
              projectView === "grid" ? (
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {visibleProjects.map((project) => (
                    <ProjectCardLink
                      key={project.id}
                      project={project}
                      canPinProjects={canPinProjects}
                    />
                  ))}
                </div>
              ) : (
                <div className="space-y-3">
                  {visibleProjects.map((project) => (
                    <ProjectRowLink
                      key={project.id}
                      project={project}
                      canPinProjects={canPinProjects}
                    />
                  ))}
                </div>
              )
            ) : (
              <div className="rounded-lg border p-6 text-center">
                <p className="font-medium">No projects yet</p>
                <p className="text-muted-foreground text-sm">
                  Projects tied to this initiative will appear here.
                </p>
              </div>
            )
          ) : null}
        </TabsContent>
      </Tabs>
    </div>
  );
};
