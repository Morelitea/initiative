import { Link, useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useProject } from "@/hooks/useProjects";
import { useGuildPath } from "@/lib/guildUrl";
import { ProjectTaskStatusesManager } from "@/components/projects/ProjectTaskStatusesManager";
import { ProjectSettingsDetailsTab } from "@/components/projects/settings/ProjectSettingsDetailsTab";
import { ProjectSettingsAccessTab } from "@/components/projects/settings/ProjectSettingsAccessTab";
import { ProjectSettingsAdvancedTab } from "@/components/projects/settings/ProjectSettingsAdvancedTab";

export const ProjectSettingsPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId: string };
  const parsedProjectId = Number(projectId);
  const { user } = useAuth();
  const gp = useGuildPath();
  const { t } = useTranslation("projects");

  const projectQuery = useProject(Number.isFinite(parsedProjectId) ? parsedProjectId : null);

  const initiativesQuery = useInitiatives({ enabled: user?.role === "admin" });

  const project = projectQuery.data;

  if (!Number.isFinite(parsedProjectId)) {
    return <p className="text-destructive">{t("detail.invalidProjectId")}</p>;
  }

  const initiativesLoading = user?.role === "admin" ? initiativesQuery.isLoading : false;

  if (projectQuery.isLoading || initiativesLoading) {
    return <p className="text-muted-foreground text-sm">{t("settings.loading")}</p>;
  }

  if (projectQuery.isError || !project) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">{t("settings.loadError")}</p>
        <Button asChild variant="link" className="px-0">
          <Link to={gp("/projects")}>{t("settings.backToProjects")}</Link>
        </Button>
      </div>
    );
  }

  const isOwner = project.owner_id === user?.id;
  const myLevel = project.my_permission_level;
  // Pure DAC: write access requires owner or write permission level
  const hasWriteAccess = myLevel === "owner" || myLevel === "write";
  // Pure DAC: write permission grants access to manage settings
  const canManageTaskStatuses = hasWriteAccess;
  const canManageAccess = hasWriteAccess;
  const canWriteProject = hasWriteAccess;

  if (!canManageAccess && !canWriteProject) {
    return (
      <div className="space-y-4">
        <Button asChild variant="link" className="px-0">
          <Link to={gp(`/projects/${project.id}`)}>{t("settings.backToProject")}</Link>
        </Button>
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>{t("settings.title")}</CardTitle>
            <CardDescription>{t("settings.noPermission")}</CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const projectDisplayName = project.icon ? `${project.icon} ${project.name}` : project.name;

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          {project.initiative && (
            <>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to={gp(`/initiatives/${project.initiative.id}`)}>
                    {project.initiative.name}
                  </Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
            </>
          )}
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp(`/projects/${project.id}`)}>{project.name}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{t("settings.breadcrumbSettings")}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t("settings.title")}</h1>
        <p className="text-muted-foreground">
          {t("settings.description", { name: projectDisplayName })}
        </p>
      </div>

      <Tabs defaultValue="details" className="space-y-4">
        <TabsList className="w-full max-w-xl justify-start">
          <TabsTrigger value="details">{t("settings.tabDetails")}</TabsTrigger>
          {canManageAccess ? (
            <TabsTrigger value="access">{t("settings.tabAccess")}</TabsTrigger>
          ) : null}
          <TabsTrigger value="task-statuses">{t("settings.tabTaskStatuses")}</TabsTrigger>
          <TabsTrigger value="advanced">{t("settings.tabAdvanced")}</TabsTrigger>
        </TabsList>

        {/* ── Details tab ── */}
        <ProjectSettingsDetailsTab
          project={project}
          projectId={parsedProjectId}
          canWriteProject={canWriteProject}
          isAdmin={user?.role === "admin"}
          initiatives={initiativesQuery.data}
          initiativesError={initiativesQuery.isError}
        />

        {/* ── Access tab ── */}
        {canManageAccess ? (
          <ProjectSettingsAccessTab project={project} projectId={parsedProjectId} />
        ) : null}

        {/* ── Task statuses tab ── */}
        <TabsContent value="task-statuses">
          <ProjectTaskStatusesManager
            projectId={project.id}
            canManage={Boolean(canManageTaskStatuses)}
          />
        </TabsContent>

        {/* ── Advanced tab ── */}
        <ProjectSettingsAdvancedTab
          project={project}
          projectId={parsedProjectId}
          canWriteProject={canWriteProject}
          isOwner={isOwner}
        />
      </Tabs>
    </div>
  );
};
