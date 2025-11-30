import { useMemo } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { apiClient } from "@/api/client";
import { Markdown } from "@/components/Markdown";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { queryClient } from "@/lib/queryClient";
import { Project } from "@/types/api";

export const ArchivePage = () => {
  const { user } = useAuth();
  const managedInitiatives = useMemo(
    () =>
      user?.initiative_roles?.filter((assignment) => assignment.role === "project_manager") ?? [],
    [user]
  );
  const canManageProjects = user?.role === "admin" || managedInitiatives.length > 0;

  const archivedProjectsQuery = useQuery<Project[]>({
    queryKey: ["projects", "archived"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/", { params: { archived: true } });
      return response.data;
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

  if (archivedProjectsQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading archived projects…</p>;
  }

  if (archivedProjectsQuery.isError) {
    return <p className="text-destructive text-sm">Unable to load archived projects.</p>;
  }

  const projects = archivedProjectsQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Archived projects</h1>
        <p className="text-muted-foreground">Reopen an initiative when the work picks back up.</p>
      </div>

      {projects.length === 0 ? (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>No archived projects</CardTitle>
            <CardDescription>Active projects stay on the main projects tab.</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {projects.map((project) => (
            <Card key={project.id} className="shadow-sm">
              <CardHeader>
                <CardTitle className="text-xl">{project.name}</CardTitle>
                {project.description ? (
                  <Markdown content={project.description} className="text-sm" />
                ) : null}
              </CardHeader>
              <CardContent className="text-muted-foreground space-y-2 text-sm">
                {project.initiative ? <p>Initiative: {project.initiative.name}</p> : null}
                <p>
                  Archived at:{" "}
                  {project.archived_at ? new Date(project.archived_at).toLocaleString() : "Unknown"}
                </p>
              </CardContent>
              <CardFooter className="flex flex-wrap gap-3">
                <Button asChild variant="link" className="px-0">
                  <Link to={`/projects/${project.id}`}>View details</Link>
                </Button>
                {canManageProjects ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => unarchiveProject.mutate(project.id)}
                    disabled={unarchiveProject.isPending}
                  >
                    Unarchive
                  </Button>
                ) : null}
              </CardFooter>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};
