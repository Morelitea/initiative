import { Link } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

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
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useArchivedProjects, useUnarchiveProject } from "@/hooks/useProjects";
import { guildPath } from "@/lib/guildUrl";
import { Capability, hasCapability } from "@/lib/permissions";

export const ArchivePage = () => {
  const { t } = useTranslation("projects");
  const { user } = useAuth();
  const { activeGuildId } = useGuilds();
  // Same shared access helper ProjectsPage uses — honors guild-admin / PAM
  // grants, so we derive manager state from guild-scoped initiative data rather
  // than user.initiative_roles (no longer populated on the /users/me object).
  const { filterVisible, permissionsFor } = useInitiativeAccess();
  const initiativesQuery = useInitiatives();

  // Helper to create guild-scoped paths
  const gp = (path: string) => (activeGuildId ? guildPath(activeGuildId, path) : path);
  const canManageProjects = useMemo(() => {
    if (hasCapability(user, Capability.dataBypass)) return true;
    if (!initiativesQuery.data) return false;
    return filterVisible(initiativesQuery.data).some(
      (initiative) => permissionsFor(initiative).canCreateProjects
    );
  }, [user, initiativesQuery.data, filterVisible, permissionsFor]);

  const archivedProjectsQuery = useArchivedProjects();

  const unarchiveProject = useUnarchiveProject();

  if (archivedProjectsQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("archived.loading")}</p>;
  }

  if (archivedProjectsQuery.isError) {
    return <p className="text-destructive text-sm">{t("archived.loadError")}</p>;
  }

  const projects = archivedProjectsQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-semibold text-3xl tracking-tight">{t("archived.title")}</h1>
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
              <CardContent className="space-y-2 text-muted-foreground text-sm">
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
