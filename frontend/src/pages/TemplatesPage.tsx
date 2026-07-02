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
import { useTemplateProjects, useUpdateProject } from "@/hooks/useProjects";
import { guildPath } from "@/lib/guildUrl";
import { Capability, hasCapability } from "@/lib/permissions";

export const TemplatesPage = () => {
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

  const templatesQuery = useTemplateProjects();

  const deactivateTemplate = useUpdateProject();

  if (templatesQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("templates.loading")}</p>;
  }

  if (templatesQuery.isError) {
    return <p className="text-destructive text-sm">{t("templates.loadError")}</p>;
  }

  const projects = templatesQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-semibold text-3xl tracking-tight">{t("tabs.templates")}</h1>
        <p className="text-muted-foreground">{t("templates.description")}</p>
      </div>

      {projects.length === 0 ? (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>{t("templates.noTemplates")}</CardTitle>
            <CardDescription>{t("templates.noTemplatesDescription")}</CardDescription>
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
                  <p>{t("templates.initiativeLabel", { name: project.initiative.name })}</p>
                ) : null}
                <p>
                  {t("templates.lastUpdated", {
                    date: new Date(project.updated_at).toLocaleString(),
                  })}
                </p>
              </CardContent>
              <CardFooter className="flex flex-wrap gap-3">
                <Button asChild variant="link" className="px-0">
                  <Link to={gp(`/projects/${project.id}`)}>{t("templates.viewTemplate")}</Link>
                </Button>
                {canManageProjects ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() =>
                      deactivateTemplate.mutate({
                        projectId: project.id,
                        data: { is_template: false },
                      })
                    }
                    disabled={deactivateTemplate.isPending}
                  >
                    {t("templates.stopUsingAsTemplate")}
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
