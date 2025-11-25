import { useEffect, useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Settings } from "lucide-react";

import { apiClient } from "@/api/client";
import { ProjectOverviewCard } from "@/components/projects/ProjectOverviewCard";
import { ProjectTasksSection } from "@/components/projects/ProjectTasksSection";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { queryClient } from "@/lib/queryClient";
import type { Project, Task, User } from "@/types/api";

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
    project.members.forEach((member) => allowed.add(member.user_id));
    project.initiative?.members?.forEach((member) => allowed.add(member.id));

    return allUsers
      .filter((item) => allowed.has(item.id))
      .map((item) => ({
        id: item.id,
        label: item.full_name ?? item.email,
      }));
  }, [usersQuery.data, projectQuery.data]);

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

  if (projectQuery.isLoading || tasksQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading project…</p>;
  }

  const project = projectQuery.data;
  if (projectQuery.isError || tasksQuery.isError || !project) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Unable to load project.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  const membershipRole = project.members.find((member) => member.user_id === user?.id)?.role;
  const userProjectRole =
    (user?.role as "admin" | "project_manager" | "member" | undefined) ?? undefined;
  const projectWriteRoles = project.write_roles ?? [];

  const canManageSettings =
    user?.role === "admin" || membershipRole === "admin" || membershipRole === "project_manager";
  const canWriteProject =
    user?.role === "admin" ||
    (membershipRole ? projectWriteRoles.includes(membershipRole) : false) ||
    (userProjectRole ? projectWriteRoles.includes(userProjectRole) : false);
  const projectIsArchived = project.is_archived ?? false;
  const canEditTaskDetails = Boolean(project && canWriteProject && !projectIsArchived);

  const handleTaskClick = (taskId: number) => {
    if (!canEditTaskDetails) {
      return;
    }
    navigate(`/tasks/${taskId}/edit`);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="link" className="px-0">
          <Link to="/">← Back to projects</Link>
        </Button>
        {canManageSettings ? (
          <Button
            asChild
            variant="ghost"
            size="icon"
            className="text-muted-foreground hover:text-foreground"
            aria-label="Open project settings"
          >
            <Link to={`/projects/${project.id}/settings`}>
              <Settings className="h-5 w-5" />
            </Link>
          </Button>
        ) : null}
      </div>
      <ProjectOverviewCard project={project} projectIsArchived={projectIsArchived} />
      <ProjectTasksSection
        projectId={project.id}
        tasks={tasksQuery.data ?? []}
        userOptions={userOptions}
        canEditTaskDetails={canEditTaskDetails}
        canWriteProject={Boolean(canWriteProject)}
        projectIsArchived={projectIsArchived}
        onTaskClick={handleTaskClick}
      />
    </div>
  );
};
