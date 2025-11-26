import { useMemo } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

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
import { useAuth } from "../hooks/useAuth";
import { queryClient } from "../lib/queryClient";
import { Project } from "../types/api";

export const TemplatesPage = () => {
  const { user } = useAuth();
  const managedInitiatives = useMemo(
    () =>
      user?.initiative_roles?.filter((assignment) => assignment.role === "project_manager") ?? [],
    [user]
  );
  const canManageProjects = user?.role === "admin" || managedInitiatives.length > 0;

  const templatesQuery = useQuery<Project[]>({
    queryKey: ["projects", "templates"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/", { params: { template: true } });
      return response.data;
    },
  });

  const deactivateTemplate = useMutation({
    mutationFn: async (projectId: number) => {
      await apiClient.patch(`/projects/${projectId}`, { is_template: false });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects", "templates"] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  if (templatesQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading templates…</p>;
  }

  if (templatesQuery.isError) {
    return <p className="text-sm text-destructive">Unable to load templates.</p>;
  }

  const projects = templatesQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Project templates</h1>
        <p className="text-muted-foreground">
          Standardize best practices and quickly spin up new initiatives using reusable templates.
        </p>
      </div>

      {projects.length === 0 ? (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>No templates available</CardTitle>
            <CardDescription>
              Create a template from any project in the project settings page.
            </CardDescription>
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
              <CardContent className="space-y-2 text-sm text-muted-foreground">
                {project.initiative ? <p>Initiative: {project.initiative.name}</p> : null}
                <p>Last updated: {new Date(project.updated_at).toLocaleString()}</p>
              </CardContent>
              <CardFooter className="flex flex-wrap gap-3">
                <Button asChild variant="link" className="px-0">
                  <Link to={`/projects/${project.id}`}>View template</Link>
                </Button>
                {canManageProjects ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => deactivateTemplate.mutate(project.id)}
                    disabled={deactivateTemplate.isPending}
                  >
                    Stop using as template
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
