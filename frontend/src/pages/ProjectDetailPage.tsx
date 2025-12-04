import { useEffect, useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Settings } from "lucide-react";

import { apiClient } from "@/api/client";
import { ProjectOverviewCard } from "@/components/projects/ProjectOverviewCard";
import { ProjectTasksSection } from "@/components/projects/ProjectTasksSection";
import { ProjectDocumentsSection } from "@/components/projects/ProjectDocumentsSection";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { queryClient } from "@/lib/queryClient";
import type { Project, ProjectTaskStatus, Task, User } from "@/types/api";

export const ProjectDetailPage = () => {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const parsedProjectId = Number(projectId);

  const projectQuery = useQuery<Project>({
    queryKey: ["projects", parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Project>(`/projects/${parsedProjectId}`);
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  const tasksQuery = useQuery<Task[]>({
    queryKey: ["tasks", parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Task[]>("/tasks/", {
        params: { project_id: parsedProjectId },
      });
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

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
        await queryClient.invalidateQueries({ queryKey: ["projects", "recent"] });
      } catch (error) {
        console.error("Failed to record project view", error);
      }
    };
    void recordView();
  }, [viewedProjectId]);

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
    project.permissions.forEach((permission) => allowed.add(permission.user_id));
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
          <Link to="/">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  if (projectQuery.isLoading || tasksQuery.isLoading || taskStatusesQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading project…</p>;
  }

  if (projectQuery.isError || tasksQuery.isError || taskStatusesQuery.isError || !project) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Unable to load project.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  const initiativeMembership = project.initiative?.members?.find(
    (member) => member.user.id === user?.id
  );
  const isOwner = project.owner_id === user?.id;
  const isInitiativePm = initiativeMembership?.role === "project_manager";
  const hasExplicitWrite = project.permissions.some(
    (permission) => permission.user_id === user?.id
  );
  const hasImplicitWrite = Boolean(project.members_can_write && initiativeMembership);

  const canManageSettings = user?.role === "admin" || isOwner || isInitiativePm;
  const canWriteProject =
    user?.role === "admin" || isOwner || isInitiativePm || hasExplicitWrite || hasImplicitWrite;
  const canViewTaskDetails = Boolean(project && (canWriteProject || initiativeMembership));
  const projectIsArchived = project.is_archived ?? false;
  const canEditTaskDetails = Boolean(project && canWriteProject && !projectIsArchived);

  const handleTaskClick = (taskId: number) => {
    if (!canViewTaskDetails) {
      return;
    }
    navigate(`/tasks/${taskId}`);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="link" className="px-0">
          <Link to="/">← Back to projects</Link>
        </Button>
        {canManageSettings ? (
          <Button asChild variant="outline" size="sm" aria-label="Open project settings">
            <Link to={`/projects/${project.id}/settings`}>
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
        canEdit={Boolean(canWriteProject && !projectIsArchived)}
      />
      <ProjectTasksSection
        projectId={project.id}
        tasks={tasksQuery.data ?? []}
        taskStatuses={taskStatusesQuery.data ?? []}
        userOptions={userOptions}
        canEditTaskDetails={canEditTaskDetails}
        canWriteProject={Boolean(canWriteProject)}
        projectIsArchived={projectIsArchived}
        canViewTaskDetails={canViewTaskDetails}
        onTaskClick={handleTaskClick}
      />
    </div>
  );
};
