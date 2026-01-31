import { useCallback, useEffect, useMemo } from "react";
import { Link, useRouter, useParams } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Settings } from "lucide-react";

import { apiClient } from "@/api/client";
import { PullToRefresh } from "@/components/PullToRefresh";
import { ProjectOverviewCard } from "@/components/projects/ProjectOverviewCard";
import { ProjectTasksSection } from "@/components/projects/ProjectTasksSection";
import { ProjectDocumentsSection } from "@/components/projects/ProjectDocumentsSection";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { queryClient } from "@/lib/queryClient";
import type { Project, ProjectTaskStatus, User } from "@/types/api";

export const ProjectDetailPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId: string };
  const router = useRouter();
  const { user } = useAuth();
  const { activeGuildId } = useGuilds();
  const localQueryClient = useQueryClient();
  const parsedProjectId = Number(projectId);

  const handleRefresh = useCallback(async () => {
    await Promise.all([
      localQueryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] }),
      localQueryClient.invalidateQueries({ queryKey: ["tasks", parsedProjectId] }),
      localQueryClient.invalidateQueries({
        queryKey: ["projects", parsedProjectId, "task-statuses"],
      }),
    ]);
  }, [localQueryClient, parsedProjectId]);

  const projectQuery = useQuery<Project>({
    queryKey: ["project", parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Project>(`/projects/${parsedProjectId}`);
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  // Tasks query is now inside ProjectTasksSection to support server-side filtering

  const taskStatusesQuery = useQuery<ProjectTaskStatus[]>({
    queryKey: ["projects", parsedProjectId, "task-statuses"],
    queryFn: async () => {
      const response = await apiClient.get<ProjectTaskStatus[]>(
        `/projects/${parsedProjectId}/task-statuses/`
      );
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  const usersQuery = useQuery<User[]>({
    queryKey: ["users"],
    queryFn: async () => {
      const response = await apiClient.get<User[]>("/users/");
      return response.data;
    },
  });

  const viewedProjectId = projectQuery.data?.id;
  useEffect(() => {
    if (!viewedProjectId) {
      return;
    }
    const recordView = async () => {
      try {
        await apiClient.post(`/projects/${viewedProjectId}/view`);
        await queryClient.invalidateQueries({ queryKey: ["projects", activeGuildId, "recent"] });
      } catch (error) {
        console.error("Failed to record project view", error);
      }
    };
    void recordView();
  }, [viewedProjectId, activeGuildId]);

  const userOptions = useMemo(() => {
    const project = projectQuery.data;
    const allUsers = usersQuery.data ?? [];
    if (!project) {
      return allUsers.map((item) => ({
        id: item.id,
        label: item.full_name ?? item.email,
      }));
    }

    const allowed = new Set<number>();
    allowed.add(project.owner_id);
    project?.permissions?.forEach((permission) => allowed.add(permission.user_id));
    project.initiative?.members?.forEach((member) => {
      if (member.user) {
        allowed.add(member.user.id);
      }
    });

    return allUsers
      .filter((item) => allowed.has(item.id))
      .map((item) => ({
        id: item.id,
        label: item.full_name ?? item.email,
      }));
  }, [usersQuery.data, projectQuery.data]);

  const project = projectQuery.data;
  const projectName = project?.name;
  useEffect(() => {
    if (typeof document === "undefined" || !projectName) {
      return;
    }
    const previousTitle = document.title || "Initiative";
    document.title = `${projectName} - Initiative`;
    return () => {
      document.title = previousTitle;
    };
  }, [projectName]);

  if (!Number.isFinite(parsedProjectId)) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Invalid project id.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/projects">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  if (projectQuery.isLoading || taskStatusesQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading project…</p>;
  }

  if (projectQuery.isError || taskStatusesQuery.isError || !project) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Unable to load project.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/projects">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  const initiativeMembership = project.initiative?.members?.find(
    (member) => member.user.id === user?.id
  );
  const isOwner = project.owner_id === user?.id;
  const isInitiativePm = initiativeMembership?.role === "project_manager";
  const userPermission = project?.permissions?.find((p) => p.user_id === user?.id);
  const hasWritePermission = userPermission?.level === "owner" || userPermission?.level === "write";

  const canManageSettings = user?.role === "admin" || isOwner || isInitiativePm;
  const canWriteProject = user?.role === "admin" || isInitiativePm || hasWritePermission;
  const canCreateDocuments = user?.role === "admin" || isOwner || isInitiativePm;
  const canAttachDocuments = canWriteProject;
  const canViewTaskDetails = Boolean(
    project && (user?.role === "admin" || isInitiativePm || userPermission)
  );
  const projectIsArchived = project.is_archived ?? false;
  const canEditTaskDetails = Boolean(project && canWriteProject && !projectIsArchived);

  const handleTaskClick = (taskId: number) => {
    if (!canViewTaskDetails) {
      return;
    }
    router.navigate({ to: "/tasks/$taskId", params: { taskId: String(taskId) } });
  };

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Breadcrumb>
            <BreadcrumbList>
              {project.initiative && (
                <>
                  <BreadcrumbItem>
                    <BreadcrumbLink asChild>
                      <Link
                        to="/initiatives/$initiativeId"
                        params={{ initiativeId: String(project.initiative.id) }}
                      >
                        {project.initiative.name}
                      </Link>
                    </BreadcrumbLink>
                  </BreadcrumbItem>
                  <BreadcrumbSeparator />
                </>
              )}
              <BreadcrumbItem>
                <BreadcrumbPage>{project.name}</BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
          {canManageSettings ? (
            <Button asChild variant="outline" size="sm" aria-label="Open project settings">
              <Link to="/projects/$projectId/settings" params={{ projectId: String(project.id) }}>
                <Settings className="h-5 w-5" /> Project Settings
              </Link>
            </Button>
          ) : null}
        </div>
        <ProjectOverviewCard project={project} projectIsArchived={projectIsArchived} />
        <ProjectDocumentsSection
          projectId={project.id}
          initiativeId={project.initiative_id}
          documents={project.documents ?? []}
          canCreate={Boolean(canCreateDocuments && !projectIsArchived)}
          canAttach={Boolean(canAttachDocuments && !projectIsArchived)}
        />
        <ProjectTasksSection
          projectId={project.id}
          taskStatuses={taskStatusesQuery.data ?? []}
          userOptions={userOptions}
          canEditTaskDetails={canEditTaskDetails}
          canWriteProject={Boolean(canWriteProject)}
          projectIsArchived={projectIsArchived}
          canViewTaskDetails={canViewTaskDetails}
          onTaskClick={handleTaskClick}
        />
      </div>
    </PullToRefresh>
  );
};
