import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

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
import { useGuilds } from "@/hooks/useGuilds";
import { queryClient } from "@/lib/queryClient";
import { guildPath } from "@/lib/guildUrl";
import { Project } from "@/types/api";

export const ArchivePage = () => {
  const { t } = useTranslation("projects");
  const { user } = useAuth();
  const { activeGuildId } = useGuilds();

  // Helper to create guild-scoped paths
  const gp = (path: string) => (activeGuildId ? guildPath(activeGuildId, path) : path);
  const managedInitiatives = useMemo(
    () =>
      user?.initiative_roles?.filter((assignment) => assignment.role === "project_manager") ?? [],
    [user]
  );
  const canManageProjects = user?.role === "admin" || managedInitiatives.length > 0;

  const archivedProjectsQuery = useQuery<Project[]>({
    queryKey: ["projects", "archived", { guildId: activeGuildId }],
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
    return <p className="text-muted-foreground text-sm">{t("archived.loading")}</p>;
  }

  if (archivedProjectsQuery.isError) {
    return <p className="text-destructive text-sm">{t("archived.loadError")}</p>;
  }

  const projects = archivedProjectsQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t("archived.title")}</h1>
        <p className="text-muted-foreground">{t("archived.subtitle")}</p>
      </div>

      {projects.length === 0 ? (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>{t("archived.noArchived")}</CardTitle>
            <CardDescription>{t("archived.noArchivedDescriptionAlt")}</CardDescription>
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
                {project.initiative ? (
                  <p>{t("archived.initiativeLabel", { name: project.initiative.name })}</p>
                ) : null}
                <p>
                  {project.archived_at
                    ? t("archived.archivedAt", {
                        date: new Date(project.archived_at).toLocaleString(),
                      })
                    : t("archived.archivedAtUnknown")}
                </p>
              </CardContent>
              <CardFooter className="flex flex-wrap gap-3">
                <Button asChild variant="link" className="px-0">
                  <Link to={gp(`/projects/${project.id}`)}>{t("archived.viewDetails")}</Link>
                </Button>
                {canManageProjects ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => unarchiveProject.mutate(project.id)}
                    disabled={unarchiveProject.isPending}
                  >
                    {t("archived.unarchive")}
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
